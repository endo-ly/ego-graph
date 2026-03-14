package dev.egograph.shared.core.platform.terminal

import android.content.ClipboardManager
import android.content.Context
import android.graphics.Color
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.inputmethod.InputMethodManager
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.ByteArrayInputStream
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs
import kotlin.math.max

private const val TERMINAL_HTML_ASSET_PATH = "xterm/terminal.html"
private const val TERMINAL_HTML_ASSET_URL = "file:///android_asset/$TERMINAL_HTML_ASSET_PATH"
private const val TERMINAL_DARK_BACKGROUND = "#1e1e1e"
private const val TERMINAL_LIGHT_BACKGROUND = "#FFFFFF"
private const val MIN_TAP_TOLERANCE_PX = 2f
private const val MIN_VERTICAL_SCROLL_DELTA_PX = 1f
private const val TERMINAL_WEBVIEW_LOG_TAG = "TerminalWebView"

private enum class TouchDragDirection {
    UNDETERMINED,
    HORIZONTAL,
    VERTICAL,
}

/**
 * Android 向け TerminalWebView 実装。
 *
 * 役割:
 * - xterm 画面 (terminal.html) の表示
 * - JavaScript ブリッジによる接続/入出力連携
 * - タップ時のみフォーカスするタッチ制御
 */
class AndroidTerminalWebView(
    private val context: Context,
) : TerminalWebView {
    private val terminalWebView: WebView by lazy { createWebView() }
    private val connectionStateMutable = MutableStateFlow(false)
    private val errorsMutable = kotlinx.coroutines.flow.MutableSharedFlow<String>(replay = 0)

    @Volatile
    private var currentWsUrl: String? = null

    @Volatile
    private var currentWsToken: String? = null

    private val isPageReady = AtomicBoolean(false)
    private val isTerminalReady = AtomicBoolean(false)

    private val mainHandler = Handler(Looper.getMainLooper())
    private val cssPixelDensity: Float = context.resources.displayMetrics.density.coerceAtLeast(1f)
    private val touchSlopPx: Float = ViewConfiguration.get(context).scaledTouchSlop.toFloat()
    private val tapMoveTolerancePx: Float = max(MIN_TAP_TOLERANCE_PX, touchSlopPx * 0.25f)

    private var touchLastY: Float? = null
    private var touchLastX: Float? = null
    private var touchStartX: Float = 0f
    private var touchStartY: Float = 0f
    private var hasMoved: Boolean = false
    private var touchDragDirection: TouchDragDirection = TouchDragDirection.UNDETERMINED

    override val connectionState: Flow<Boolean> = connectionStateMutable.asStateFlow()
    override val errors: Flow<String> = errorsMutable

    /**
     * UI スレッドでの実行を保証する。
     */
    private fun runOnMainThread(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            block()
        } else {
            mainHandler.post(block)
        }
    }

    /**
     * JavaScript を WebView に評価させる。
     */
    private fun evaluateJavascript(script: String) {
        terminalWebView.evaluateJavascript(script.trimIndent(), null)
    }

    /**
     * Android の実ピクセルを WebView/CSS ピクセルへ変換する。
     *
     * terminal.html 側の style / clientHeight / scrollTop は CSS px 基準のため、
     * 端末密度ぶん縮めて渡さないと過大なオフセットになる。
     */
    private fun toCssPixels(devicePixels: Float): Float = devicePixels / cssPixelDensity

    /**
     * TerminalAPI 呼び出しの共通テンプレート。
     */
    private fun executeTerminalApiScript(script: String) {
        runOnMainThread {
            evaluateJavascript(
                """
                if (window.TerminalAPI) {
                    $script
                }
                """,
            )
        }
    }

    /**
     * xterm の 1 行スクロールへ変換するため、ピクセル差分を JavaScript 側へ渡す。
     */
    private fun sendScrollByPixels(pixelDelta: Float) {
        if (pixelDelta == 0f) {
            return
        }
        evaluateJavascript(
            """
            if (window.TerminalAPI && typeof window.TerminalAPI.scrollByPixels === 'function') {
                window.TerminalAPI.scrollByPixels($pixelDelta);
            }
            """,
        )
    }

    /**
     * タッチ開始時の基準点を記録する。
     */
    private fun onTouchDown(event: MotionEvent) {
        touchLastY = event.y
        touchLastX = event.x
        touchStartX = event.x
        touchStartY = event.y
        hasMoved = false
        touchDragDirection = TouchDragDirection.UNDETERMINED
    }

    /**
     * 移動量がタップ許容を超えているかを判定する。
     */
    private fun movedBeyondTapTolerance(
        x: Float,
        y: Float,
    ): Boolean {
        val totalDeltaX = abs(x - touchStartX)
        val totalDeltaY = abs(y - touchStartY)
        return totalDeltaX > tapMoveTolerancePx || totalDeltaY > tapMoveTolerancePx
    }

    /**
     * UP 時点での最終タップ判定。
     *
     * MOVE が少ない端末でも取りこぼしを避けるため、終了座標でも再判定する。
     */
    private fun isTapOnActionUp(event: MotionEvent): Boolean {
        if (hasMoved) {
            return false
        }
        return !movedBeyondTapTolerance(event.x, event.y)
    }

    /**
     * タッチ追跡状態を初期化する。
     */
    private fun clearTouchTracking() {
        touchLastY = null
        touchLastX = null
        touchDragDirection = TouchDragDirection.UNDETERMINED
    }

    /**
     * 現在の移動方向を推定する。
     *
     * 一定距離を超えるまでは UNDETERMINED にして、誤判定を避ける。
     */
    private fun resolveTouchDragDirection(event: MotionEvent): TouchDragDirection {
        if (touchDragDirection != TouchDragDirection.UNDETERMINED) {
            return touchDragDirection
        }
        if (!movedBeyondTapTolerance(event.x, event.y)) {
            return TouchDragDirection.UNDETERMINED
        }

        val totalDeltaX = abs(event.x - touchStartX)
        val totalDeltaY = abs(event.y - touchStartY)
        touchDragDirection =
            if (totalDeltaX > totalDeltaY) {
                TouchDragDirection.HORIZONTAL
            } else {
                TouchDragDirection.VERTICAL
            }
        hasMoved = true
        return touchDragDirection
    }

    /**
     * MOVE を処理して、イベントを WebView 側で消費するか返す。
     *
     * 縦方向優位の移動だけをスクロールとして扱い、同時に hasMoved を立てる。
     * これにより ACTION_UP でタップ誤判定されるのを防ぐ。
     */
    private fun onTouchMove(event: MotionEvent): Boolean {
        val direction = resolveTouchDragDirection(event)

        if (direction == TouchDragDirection.HORIZONTAL) {
            touchLastY = event.y
            touchLastX = event.x
            return false
        }

        var handledVerticalMove = false
        val previousY = touchLastY
        val previousX = touchLastX

        if (previousY != null && previousX != null) {
            val deltaY = previousY - event.y
            val deltaX = previousX - event.x
            if (abs(deltaY) > abs(deltaX) && abs(deltaY) >= MIN_VERTICAL_SCROLL_DELTA_PX) {
                sendScrollByPixels(deltaY)
                handledVerticalMove = true
                hasMoved = true
                touchDragDirection = TouchDragDirection.VERTICAL
            }
        }

        if (!hasMoved && movedBeyondTapTolerance(event.x, event.y)) {
            hasMoved = true
        }

        touchLastY = event.y
        touchLastX = event.x
        return handledVerticalMove
    }

    /**
     * 親コンテナの横スワイプ干渉を制御する。
     */
    private fun setParentIntercept(
        view: View,
        disallow: Boolean,
    ) {
        view.parent?.requestDisallowInterceptTouchEvent(disallow)
    }

    /**
     * WebView 上のタッチを一箇所で正規化して扱う。
     *
     * - タップ: WebView 側で処理してキーボードを開く
     * - 縦スワイプ: WebView 側でスクロール処理
     * - 横スワイプ: 親コンテナへ委譲（チャット戻りジェスチャー用）
     */
    private fun handleTerminalTouch(
        view: View,
        event: MotionEvent,
    ): Boolean =
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                onTouchDown(event)
                setParentIntercept(view, false)
                true
            }

            MotionEvent.ACTION_MOVE -> {
                onTouchMove(event)
                when (touchDragDirection) {
                    TouchDragDirection.HORIZONTAL -> {
                        setParentIntercept(view, false)
                        false
                    }

                    TouchDragDirection.VERTICAL -> {
                        setParentIntercept(view, true)
                        true
                    }

                    TouchDragDirection.UNDETERMINED -> {
                        setParentIntercept(view, false)
                        true
                    }
                }
            }

            MotionEvent.ACTION_UP -> {
                val isHorizontalSwipe = touchDragDirection == TouchDragDirection.HORIZONTAL
                if (!isHorizontalSwipe && isTapOnActionUp(event)) {
                    view.performClick()
                    focusInputAtBottomAndShowKeyboard()
                }
                clearTouchTracking()
                setParentIntercept(view, false)
                !isHorizontalSwipe
            }

            MotionEvent.ACTION_CANCEL -> {
                clearTouchTracking()
                setParentIntercept(view, false)
                true
            }

            else -> false
        }

    /**
     * WebView に対してソフトキーボード表示を要求する。
     */
    private fun showSoftKeyboard(view: View) {
        val inputMethodManager = context.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
        inputMethodManager?.showSoftInput(view, InputMethodManager.SHOW_IMPLICIT)
    }

    /**
     * xterm 末尾へフォーカスし、必要に応じてソフトキーボードを表示する。
     */
    private fun focusInputAtBottomInternal(showKeyboard: Boolean) {
        runOnMainThread {
            Log.d(TERMINAL_WEBVIEW_LOG_TAG, "focusInputAtBottomInternal(showKeyboard=$showKeyboard)")
            terminalWebView.requestFocus()
            terminalWebView.evaluateJavascript(
                """
                if (window.TerminalAPI && typeof window.TerminalAPI.focusInputAtBottom === 'function') {
                    window.TerminalAPI.focusInputAtBottom();
                }
                """.trimIndent(),
            ) {
                if (showKeyboard) {
                    showSoftKeyboard(terminalWebView)
                }
            }
        }
    }

    /**
     * タップ時専用:
     * - フォーカスを末尾へ寄せる
     * - ソフトキーボードを明示的に開く
     */
    private fun focusInputAtBottomAndShowKeyboard() {
        focusInputAtBottomInternal(showKeyboard = true)
    }

    /**
     * WebView 基本設定を適用する。
     */
    private fun configureWebSettings(webSettings: WebSettings) {
        webSettings.javaScriptEnabled = true
        webSettings.domStorageEnabled = true
        webSettings.allowContentAccess = true
        webSettings.allowFileAccess = true
        webSettings.cacheMode = WebSettings.LOAD_NO_CACHE
        webSettings.loadWithOverviewMode = false
        webSettings.useWideViewPort = false
        webSettings.textZoom = 100
        webSettings.setSupportZoom(false)
        webSettings.builtInZoomControls = false
        webSettings.displayZoomControls = false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            @Suppress("DEPRECATION")
            webSettings.forceDark = WebSettings.FORCE_DARK_OFF
        }
    }

    /**
     * terminal.html へのリクエストのみローカル asset から返す。
     */
    private fun interceptTerminalHtmlRequest(url: String): WebResourceResponse? {
        if (!url.endsWith(TERMINAL_HTML_ASSET_PATH)) {
            return null
        }
        val html = loadAssetText(TERMINAL_HTML_ASSET_PATH)
        return createResponse(html, "text/html")
    }

    /**
     * WebViewClient を構築する。
     */
    private fun createTerminalWebViewClient(): WebViewClient =
        object : WebViewClient() {
            override fun onPageFinished(
                view: WebView?,
                url: String?,
            ) {
                super.onPageFinished(view, url)
                isPageReady.set(true)
                connectIfReady()
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?,
            ) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) {
                    errorsMutable.tryEmit("Terminal page load error: ${error?.description}")
                }
            }

            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest?,
            ): WebResourceResponse? {
                val url = request?.url?.toString() ?: return super.shouldInterceptRequest(view, request)
                return interceptTerminalHtmlRequest(url) ?: super.shouldInterceptRequest(view, request)
            }
        }

    /**
     * WebChromeClient を構築する。
     */
    private fun createTerminalWebChromeClient(): WebChromeClient =
        object : WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: ConsoleMessage): Boolean {
                Log.d(
                    TERMINAL_WEBVIEW_LOG_TAG,
                    "console[${consoleMessage.messageLevel()}] ${consoleMessage.message()} " +
                        "@${consoleMessage.sourceId()}:${consoleMessage.lineNumber()}",
                )
                return false
            }
        }

    /**
     * WebView の描画設定とタッチリスナーを適用する。
     */
    private fun initializeWebViewAppearance(target: WebView) {
        target.setLayerType(View.LAYER_TYPE_SOFTWARE, null)
        target.setBackgroundColor(Color.parseColor(TERMINAL_DARK_BACKGROUND))
        target.setOnTouchListener { view, event -> handleTerminalTouch(view, event) }
    }

    /**
     * Terminal 表示用 WebView を生成する。
     */
    private fun createWebView(): WebView =
        WebView(context).apply {
            configureWebSettings(settings)
            addJavascriptInterface(TerminalJavaScriptBridge(), "TerminalBridge")
            webViewClient = createTerminalWebViewClient()
            webChromeClient = createTerminalWebChromeClient()
            initializeWebViewAppearance(this)
        }

    /**
     * HTML/JavaScript へ埋め込むための最小エスケープ。
     */
    private fun escapeHtml(text: String): String =
        text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\"", "&quot;")
            .replace("'", "&#39;")

    /**
     * JavaScript 文字列へ埋め込むためのエスケープ。
     */
    private fun escapeJsString(text: String): String =
        text
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
            .replace("\"", "\\\"")

    /**
     * asset テキストを読み込む。失敗時はエラー内容を返す。
     */
    private fun loadAssetText(path: String): String =
        try {
            context.assets
                .open(path)
                .bufferedReader()
                .use { it.readText() }
        } catch (e: Exception) {
            val message = "Failed to load asset: $path (${e.message})"
            errorsMutable.tryEmit(message)
            if (path.endsWith(TERMINAL_HTML_ASSET_PATH)) {
                """
                <!DOCTYPE html><html><body style=\"font-family:monospace;padding:16px;\">
                <h3>Terminal asset error</h3>
                <p>${escapeHtml(message)}</p>
                </body></html>
                """.trimIndent()
            } else {
                val sanitizedMessage = message.replace("*/", "* /").replace("/*", "/ *")
                "/* $sanitizedMessage */"
            }
        }

    /**
     * 文字列から WebResourceResponse を生成する。
     */
    private fun createResponse(
        data: String,
        mimeType: String,
    ): WebResourceResponse {
        val encoding = "UTF-8"
        val inputStream = ByteArrayInputStream(data.toByteArray(charset(encoding)))
        return WebResourceResponse(mimeType, encoding, inputStream)
    }

    override fun loadTerminal() {
        isPageReady.set(false)
        isTerminalReady.set(false)
        terminalWebView.clearCache(true)
        terminalWebView.loadUrl(TERMINAL_HTML_ASSET_URL)
    }

    override fun connect(
        wsUrl: String,
        wsToken: String,
    ) {
        currentWsUrl = wsUrl
        currentWsToken = wsToken
        connectIfReady()
    }

    /**
     * 接続に必要な状態が揃っているか判定する。
     */
    private fun canConnectNow(): Boolean = isPageReady.get() && isTerminalReady.get()

    /**
     * 現在保持している接続情報で connect を送る。
     */
    private fun connectIfReady() {
        val wsUrl = currentWsUrl ?: return
        val wsToken = currentWsToken ?: return
        if (!canConnectNow()) {
            return
        }

        val escapedWsUrl = escapeJsString(wsUrl)
        val escapedWsToken = escapeJsString(wsToken)
        executeTerminalApiScript(
            "window.TerminalAPI.connect('$escapedWsUrl', '$escapedWsToken');",
        )
    }

    override fun disconnect() {
        executeTerminalApiScript("window.TerminalAPI.disconnect();")
    }

    override fun sendKey(key: String) {
        val escapedKey = escapeJsString(key)
        executeTerminalApiScript("window.TerminalAPI.sendKey('$escapedKey');")
    }

    override fun pasteFromClipboard() {
        val clipboardText = readClipboardText() ?: return
        if (clipboardText.isEmpty()) {
            return
        }

        sendKey(clipboardText)
        focusInputAtBottom()
    }

    override fun setBottomScrollPadding(paddingPx: Float) {
        val sanitizedPaddingPx = paddingPx.coerceAtLeast(0f)
        val cssPaddingPx = toCssPixels(sanitizedPaddingPx)
        Log.d(
            TERMINAL_WEBVIEW_LOG_TAG,
            "setBottomScrollPadding(devicePx=$sanitizedPaddingPx, cssPx=$cssPaddingPx, density=$cssPixelDensity)",
        )
        executeTerminalApiScript(
            "window.TerminalAPI.setBottomScrollPadding($cssPaddingPx);",
        )
    }

    override fun focusInputAtBottom() {
        focusInputAtBottomInternal(showKeyboard = false)
    }

    override fun setTheme(darkMode: Boolean) {
        val backgroundColor = if (darkMode) TERMINAL_DARK_BACKGROUND else TERMINAL_LIGHT_BACKGROUND
        runOnMainThread {
            terminalWebView.setBackgroundColor(Color.parseColor(backgroundColor))
        }
    }

    /**
     * クリップボードからテキストを取得する。
     */
    private fun readClipboardText(): String? {
        val clipboardManager = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return null
        val primaryClip = clipboardManager.primaryClip ?: return null
        if (primaryClip.itemCount <= 0) {
            return null
        }

        return primaryClip.getItemAt(0).coerceToText(context)?.toString()
    }

    fun getWebView(): WebView = terminalWebView

    /**
     * JavaScript から Kotlin へ通知するブリッジ。
     *
     * すべての通知は JavaBridge スレッドから来るため、
     * UI 状態変更が必要な処理は mainHandler 経由で実行する。
     */
    inner class TerminalJavaScriptBridge {
        @JavascriptInterface
        fun onConnectionChanged(connected: Boolean) {
            mainHandler.post {
                connectionStateMutable.tryEmit(connected)
            }
        }

        @JavascriptInterface
        fun onError(error: String) {
            errorsMutable.tryEmit(error)
        }

        @JavascriptInterface
        fun onTerminalReady() {
            mainHandler.post {
                isTerminalReady.set(true)
                connectIfReady()
            }
        }
    }
}

/**
 * Android では Context が必要なため、この経路は利用しない。
 */
actual fun createTerminalWebView(): TerminalWebView = throw NotImplementedError("Use createTerminalWebView(Context) instead")

/**
 * Android 用の TerminalWebView を生成する。
 */
fun createTerminalWebView(context: Context): TerminalWebView = AndroidTerminalWebView(context)
