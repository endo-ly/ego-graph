package dev.egograph.shared.features.terminal.session

import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.core.screen.ScreenKey
import cafe.adriel.voyager.navigator.LocalNavigator
import dev.egograph.shared.core.domain.repository.TerminalRepository
import dev.egograph.shared.core.platform.PlatformPreferences
import dev.egograph.shared.core.platform.PlatformPrefsKeys
import dev.egograph.shared.core.platform.rememberKeyboardState
import dev.egograph.shared.core.settings.AppTheme
import dev.egograph.shared.core.settings.ThemeRepository
import dev.egograph.shared.features.terminal.session.components.DraggableTerminalFloatingControlPill
import dev.egograph.shared.features.terminal.session.components.SpecialKeysBar
import dev.egograph.shared.features.terminal.session.components.TerminalFloatingControlPosition
import dev.egograph.shared.features.terminal.session.components.TerminalView
import dev.egograph.shared.features.terminal.session.components.rememberTerminalWebView
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.koin.compose.koinInject

private const val TERMINAL_KEYBOARD_FOCUS_DELAY_MS = 100L
private val TERMINAL_KEYBOARD_ACCESSORY_HORIZONTAL_PADDING = 4.dp
private val TERMINAL_KEYBOARD_ACCESSORY_VERTICAL_PADDING = 6.dp
private val TERMINAL_KEYBOARD_FOCUS_BUFFER = 16.dp

/**
 * ターミナル画面
 *
 * WebSocket経由でGatewayに接続し、ターミナルエミュレーションを表示する画面。
 *
 * @property agentId エージェントID
 * @property onClose 閉じるボタンが押された時のコールバック
 */
class TerminalScreen(
    private val agentId: String,
    private val onClose: (() -> Unit)? = null,
) : Screen {
    override val key: ScreenKey
        get() = "TerminalScreen:$agentId"

    @Composable
    override fun Content() {
        TerminalContent(agentId = agentId, onClose = onClose)
    }
}

@Composable
private fun TerminalContent(
    agentId: String,
    onClose: (() -> Unit)? = null,
) {
    val navigator = requireNotNull(LocalNavigator.current)
    val webView = rememberTerminalWebView()
    val preferences = koinInject<PlatformPreferences>()
    val themeRepository = koinInject<ThemeRepository>()
    val terminalRepository = koinInject<TerminalRepository>()
    val selectedTheme by themeRepository.theme.collectAsState()
    val systemDarkTheme = isSystemInDarkTheme()
    val connectionState by webView.connectionState.collectAsState(initial = false)
    val keyboardState = rememberKeyboardState()
    val density = LocalDensity.current

    var isConnecting by remember { mutableStateOf(false) }
    var settingsError by remember { mutableStateOf<String?>(null) }
    var voiceInputError by remember { mutableStateOf<String?>(null) }
    var terminalError by remember { mutableStateOf<String?>(null) }
    var hasConnectedOnce by remember { mutableStateOf(false) }
    var reconnectAttempts by remember { mutableStateOf(0) }
    var reconnectJob by remember { mutableStateOf<Job?>(null) }
    var isCopyModeOpen by remember { mutableStateOf(false) }
    var keyboardAccessoryHeightPx by remember { mutableIntStateOf(0) }
    var floatingControlPosition by remember(agentId) { mutableStateOf<TerminalFloatingControlPosition?>(null) }
    val backoff = remember { createTerminalReconnectBackoff() }
    val coroutineScope = rememberCoroutineScope()

    val voiceInputCoordinator =
        rememberTerminalVoiceInputCoordinator(
            onRecognizedText = { recognizedText -> webView.sendKey(recognizedText) },
            onError = { message -> voiceInputError = message.ifBlank { null } },
        )

    val darkMode =
        when (selectedTheme) {
            AppTheme.DARK -> true
            AppTheme.LIGHT -> false
            AppTheme.SYSTEM -> systemDarkTheme
        }

    val terminalSettings = rememberTerminalSettings(agentId = agentId, preferences = preferences)

    LaunchedEffect(agentId) {
        preferences.putString(PlatformPrefsKeys.KEY_LAST_TERMINAL_SESSION, agentId)
    }

    LaunchedEffect(terminalSettings.error) {
        settingsError = terminalSettings.error
    }

    LaunchedEffect(webView, terminalSettings.wsUrl, agentId) {
        webView.loadTerminal()
        webView.setTheme(darkMode)
        if (!terminalSettings.wsUrl.isNullOrBlank()) {
            isConnecting = true
            val result = terminalRepository.issueWsToken(agentId)
            result
                .onSuccess { wsToken ->
                    webView.connect(terminalSettings.wsUrl, wsToken.wsToken)
                }.onFailure { error ->
                    terminalError = "Connection failed"
                    isConnecting = false
                }
        }
    }

    LaunchedEffect(webView, darkMode) {
        webView.setTheme(darkMode)
    }

    val keyboardBottomScrollPaddingPx =
        with(density) {
            if (keyboardState.isVisible) {
                keyboardState.height.toPx() + keyboardAccessoryHeightPx + TERMINAL_KEYBOARD_FOCUS_BUFFER.toPx()
            } else {
                0f
            }
        }
    val floatingControlBottomObstacleHeightPx =
        with(density) {
            if (keyboardState.isVisible) {
                keyboardState.height.toPx() + keyboardAccessoryHeightPx.toFloat()
            } else {
                0f
            }
        }

    LaunchedEffect(webView, keyboardBottomScrollPaddingPx, keyboardState.isVisible) {
        webView.setBottomScrollPadding(keyboardBottomScrollPaddingPx)
        if (keyboardState.isVisible) {
            delay(TERMINAL_KEYBOARD_FOCUS_DELAY_MS)
            webView.focusInputAtBottom()
        }
    }

    LaunchedEffect(connectionState, terminalSettings.wsUrl, agentId) {
        if (connectionState) {
            reconnectJob?.cancel()
            reconnectJob = null
            hasConnectedOnce = true
            isConnecting = false
            terminalError = null
            reconnectAttempts = 0
        } else if (
            hasConnectedOnce &&
            !terminalSettings.wsUrl.isNullOrBlank() &&
            reconnectJob?.isActive != true
        ) {
            reconnectJob =
                coroutineScope.launch {
                    while (isActive && !connectionState) {
                        val delayMs = backoff.calculateDelay(reconnectAttempts)
                        delay(delayMs)

                        if (!isActive || connectionState) {
                            break
                        }

                        reconnectAttempts++
                        isConnecting = true
                        val result = terminalRepository.issueWsToken(agentId)
                        result
                            .onSuccess { wsToken ->
                                webView.connect(terminalSettings.wsUrl, wsToken.wsToken)
                            }.onFailure {
                                isConnecting = false
                            }
                    }
                }
        }
    }

    LaunchedEffect(webView) {
        webView.errors.collect { errorMessage ->
            terminalError = errorMessage
            isConnecting = false
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            reconnectJob?.cancel()
            webView.disconnect()
        }
    }

    val displayError = settingsError ?: terminalError ?: voiceInputError
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.surfaceContainerLowest),
    ) {
        TerminalView(
            webView = webView,
            modifier =
                Modifier
                    .fillMaxSize()
                    .statusBarsPadding(),
        )

        if (isConnecting) {
            LinearProgressIndicator(
                modifier =
                    Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxWidth(),
            )
        }

        displayError?.let { error ->
            Text(
                text = error,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.align(Alignment.Center).padding(horizontal = 24.dp),
            )
        }

        if (keyboardState.isVisible) {
            Column(
                modifier =
                    Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .imePadding(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .padding(
                                horizontal = TERMINAL_KEYBOARD_ACCESSORY_HORIZONTAL_PADDING,
                                vertical = TERMINAL_KEYBOARD_ACCESSORY_VERTICAL_PADDING,
                            ).onSizeChanged { size ->
                                keyboardAccessoryHeightPx = size.height
                            },
                ) {
                    SpecialKeysBar(
                        onKeyPress = { keySequence -> webView.sendKey(keySequence) },
                        onVoiceInputClick = voiceInputCoordinator.onToggle,
                        isVoiceInputActive = voiceInputCoordinator.isActive,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }

        DraggableTerminalFloatingControlPill(
            sessionId = agentId,
            isConnected = connectionState && displayError == null,
            onBack = { onClose?.invoke() ?: navigator.pop() },
            onPaste = { webView.pasteFromClipboard() },
            onCopy = { isCopyModeOpen = true },
            position = floatingControlPosition,
            onPositionChange = { position -> floatingControlPosition = position },
            bottomObstacleHeightPx = floatingControlBottomObstacleHeightPx,
        )
    }

    if (isCopyModeOpen) {
        TerminalCopyModeSheet(
            agentId = agentId,
            onDismiss = { isCopyModeOpen = false },
        )
    }
}
