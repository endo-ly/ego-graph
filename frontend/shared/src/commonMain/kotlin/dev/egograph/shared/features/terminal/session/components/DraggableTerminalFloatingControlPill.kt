package dev.egograph.shared.features.terminal.session.components

import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.statusBars
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import kotlin.math.max
import kotlin.math.roundToInt

private val FLOATING_CONTROL_HORIZONTAL_MARGIN = 20.dp
private val FLOATING_CONTROL_VERTICAL_MARGIN = 16.dp
private val FLOATING_CONTROL_RELOCATION_GAP = 16.dp

/**
 * ターミナル操作ピルをドラッグ移動できるオーバーレイ。
 *
 * 画面外やシステムバーへ潜り込まないように位置を補正する。
 *
 * @param sessionId セッションID
 * @param isConnected 接続状態
 * @param onBack 戻るボタン押下時のコールバック
 * @param onPaste 貼り付けボタン押下時のコールバック
 * @param onCopy コピーボタン押下時のコールバック
 * @param position 現在のピル位置
 * @param onPositionChange ピル位置が変わった時のコールバック
 * @param bottomObstacleHeightPx キーボードなどで画面下から回避したい高さ
 * @param modifier Modifier
 */
@Composable
internal fun DraggableTerminalFloatingControlPill(
    sessionId: String,
    isConnected: Boolean,
    onBack: () -> Unit,
    onPaste: () -> Unit,
    onCopy: () -> Unit,
    position: TerminalFloatingControlPosition?,
    onPositionChange: (TerminalFloatingControlPosition) -> Unit,
    bottomObstacleHeightPx: Float = 0f,
    modifier: Modifier = Modifier,
) {
    val density = LocalDensity.current
    val statusBarInset = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
    val navigationBarInset = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    val latestPosition by rememberUpdatedState(position)
    val latestOnPositionChange by rememberUpdatedState(onPositionChange)
    val latestBottomObstacleHeightPx by rememberUpdatedState(bottomObstacleHeightPx)
    var controlSize by remember { mutableStateOf(IntSize.Zero) }

    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        val bounds =
            TerminalFloatingControlBounds(
                containerWidthPx = with(density) { maxWidth.toPx() },
                containerHeightPx = with(density) { maxHeight.toPx() },
                controlWidthPx = controlSize.width.toFloat(),
                controlHeightPx = controlSize.height.toFloat(),
                horizontalMarginPx = with(density) { FLOATING_CONTROL_HORIZONTAL_MARGIN.toPx() },
                verticalMarginPx = with(density) { FLOATING_CONTROL_VERTICAL_MARGIN.toPx() },
                topInsetPx = with(density) { statusBarInset.toPx() },
                bottomInsetPx = with(density) { navigationBarInset.toPx() },
            )
        val relocationGapPx = with(density) { FLOATING_CONTROL_RELOCATION_GAP.toPx() }
        val obstacle = bounds.createBottomObstacle(bottomObstacleHeightPx)

        val currentPosition =
            if (bounds.isReady) {
                resolveTerminalFloatingControlDisplayPosition(
                    position = position,
                    bounds = bounds,
                    obstacle = obstacle,
                    relocationGapPx = relocationGapPx,
                )
            } else {
                TerminalFloatingControlPosition.Zero
            }

        TerminalFloatingControlPill(
            sessionId = sessionId,
            isConnected = isConnected,
            onBack = onBack,
            onPaste = onPaste,
            onCopy = onCopy,
            modifier =
                Modifier
                    .alpha(if (bounds.isReady) 1f else 0f)
                    .offset {
                        androidx.compose.ui.unit.IntOffset(
                            x = currentPosition.xPx.roundToInt(),
                            y = currentPosition.yPx.roundToInt(),
                        )
                    }
                    .onSizeChanged { size ->
                        controlSize = size
                    }
                    .pointerInput(bounds) {
                        if (!bounds.isReady) {
                            return@pointerInput
                        }

                        var dragPosition =
                            resolveTerminalFloatingControlDisplayPosition(
                                position = latestPosition,
                                bounds = bounds,
                                obstacle = bounds.createBottomObstacle(latestBottomObstacleHeightPx),
                                relocationGapPx = relocationGapPx,
                            )

                        detectDragGestures(
                            onDragStart = {
                                dragPosition =
                                    resolveTerminalFloatingControlDisplayPosition(
                                        position = latestPosition,
                                        bounds = bounds,
                                        obstacle = bounds.createBottomObstacle(latestBottomObstacleHeightPx),
                                        relocationGapPx = relocationGapPx,
                                    )
                            },
                            onDrag = { change, dragAmount ->
                                change.consume()
                                dragPosition =
                                    clampTerminalFloatingControlDragPosition(
                                        position =
                                            dragPosition.translate(
                                                deltaX = dragAmount.x,
                                                deltaY = dragAmount.y,
                                            ),
                                        bounds = bounds,
                                        obstacle = bounds.createBottomObstacle(latestBottomObstacleHeightPx),
                                    )
                                latestOnPositionChange(dragPosition)
                            },
                        )
                    },
        )
    }
}

/**
 * フローティング操作ピルの配置計算に必要な境界情報。
 *
 * @property containerWidthPx コンテナ幅
 * @property containerHeightPx コンテナ高さ
 * @property controlWidthPx ピル幅
 * @property controlHeightPx ピル高さ
 * @property horizontalMarginPx 左右マージン
 * @property verticalMarginPx 上下マージン
 * @property topInsetPx 上部システムインセット
 * @property bottomInsetPx 下部システムインセット
 */
internal data class TerminalFloatingControlBounds(
    val containerWidthPx: Float,
    val containerHeightPx: Float,
    val controlWidthPx: Float,
    val controlHeightPx: Float,
    val horizontalMarginPx: Float,
    val verticalMarginPx: Float,
    val topInsetPx: Float = 0f,
    val bottomInsetPx: Float = 0f,
) {
    val isReady: Boolean
        get() = containerWidthPx > 0f && containerHeightPx > 0f && controlWidthPx > 0f && controlHeightPx > 0f
}

/**
 * フローティング操作ピルの左上座標。
 *
 * @property xPx X座標
 * @property yPx Y座標
 */
internal data class TerminalFloatingControlPosition(
    val xPx: Float,
    val yPx: Float,
) {
    fun translate(
        deltaX: Float,
        deltaY: Float,
    ): TerminalFloatingControlPosition = TerminalFloatingControlPosition(xPx = xPx + deltaX, yPx = yPx + deltaY)

    companion object {
        val Zero = TerminalFloatingControlPosition(xPx = 0f, yPx = 0f)
    }
}

/**
 * 一時的に回避したい矩形領域。
 *
 * @property leftPx 左端
 * @property topPx 上端
 * @property rightPx 右端
 * @property bottomPx 下端
 */
internal data class TerminalFloatingControlObstacle(
    val leftPx: Float,
    val topPx: Float,
    val rightPx: Float,
    val bottomPx: Float,
)

/**
 * 初期表示位置を返す。
 *
 * 初期状態では画面下中央に配置する。
 *
 * @param bounds 配置可能な境界情報
 * @return 下中央に寄せた初期位置
 */
internal fun defaultTerminalFloatingControlPosition(bounds: TerminalFloatingControlBounds): TerminalFloatingControlPosition {
    val minX = bounds.minX()
    val maxX = bounds.maxX()
    val x = (minX + maxX) / 2f
    val y = bounds.maxY()

    return TerminalFloatingControlPosition(xPx = x, yPx = y)
}

/**
 * 画面内に収まるように位置を補正する。
 *
 * @param position 補正前の位置
 * @param bounds 配置可能な境界情報
 * @return 画面内へ収めた位置
 */
internal fun clampTerminalFloatingControlPosition(
    position: TerminalFloatingControlPosition,
    bounds: TerminalFloatingControlBounds,
): TerminalFloatingControlPosition {
    if (!bounds.isReady) {
        return position
    }

    return TerminalFloatingControlPosition(
        xPx = position.xPx.coerceIn(bounds.minX(), bounds.maxX()),
        yPx = position.yPx.coerceIn(bounds.minY(), bounds.maxY()),
    )
}

/**
 * ドラッグ中の位置を補正する。
 *
 * 通常の画面端クランプに加えて、障害物へめり込まないようにする。
 *
 * @param position 補正前の位置
 * @param bounds 配置可能な境界情報
 * @param obstacle 一時回避領域
 * @return ドラッグ中に採用する位置
 */
internal fun clampTerminalFloatingControlDragPosition(
    position: TerminalFloatingControlPosition,
    bounds: TerminalFloatingControlBounds,
    obstacle: TerminalFloatingControlObstacle?,
): TerminalFloatingControlPosition {
    val clamped = clampTerminalFloatingControlPosition(position = position, bounds = bounds)

    if (!bounds.isReady || obstacle == null) {
        return clamped
    }

    val controlLeft = clamped.xPx
    val controlRight = clamped.xPx + bounds.controlWidthPx
    val overlapsHorizontally = controlLeft < obstacle.rightPx && controlRight > obstacle.leftPx
    val controlBottom = clamped.yPx + bounds.controlHeightPx
    val overlapsVertically = clamped.yPx < obstacle.bottomPx && controlBottom > obstacle.topPx

    if (!overlapsHorizontally || !overlapsVertically) {
        return clamped
    }

    return TerminalFloatingControlPosition(
        xPx = clamped.xPx,
        yPx = (obstacle.topPx - bounds.controlHeightPx).coerceAtLeast(bounds.minY()),
    )
}

/**
 * 表示用の最終位置を計算する。
 *
 * 通常は保存済みの位置を使い、障害物と重なる場合だけ右上寄りへ一時退避する。
 *
 * @param position 保存済みの位置
 * @param bounds 配置可能な境界情報
 * @param obstacle 一時回避領域
 * @param relocationGapPx 回避領域から離す距離
 * @return 画面上へ表示すべき位置
 */
internal fun resolveTerminalFloatingControlDisplayPosition(
    position: TerminalFloatingControlPosition?,
    bounds: TerminalFloatingControlBounds,
    obstacle: TerminalFloatingControlObstacle?,
    relocationGapPx: Float,
): TerminalFloatingControlPosition {
    val basePosition =
        clampTerminalFloatingControlPosition(
            position = position ?: defaultTerminalFloatingControlPosition(bounds),
            bounds = bounds,
        )

    if (!bounds.isReady || obstacle == null) {
        return basePosition
    }

    if (!terminalFloatingControlOverlapsObstacle(basePosition, bounds, obstacle)) {
        return basePosition
    }

    return relocatedTerminalFloatingControlPosition(bounds = bounds, obstacle = obstacle, relocationGapPx = relocationGapPx)
}

/**
 * 指定位置のピルが障害物と重なっているかを判定する。
 *
 * @param position ピル左上位置
 * @param bounds 配置可能な境界情報
 * @param obstacle 一時回避領域
 * @return 重なっていれば true
 */
internal fun terminalFloatingControlOverlapsObstacle(
    position: TerminalFloatingControlPosition,
    bounds: TerminalFloatingControlBounds,
    obstacle: TerminalFloatingControlObstacle,
): Boolean {
    if (!bounds.isReady) {
        return false
    }

    val controlLeft = position.xPx
    val controlTop = position.yPx
    val controlRight = position.xPx + bounds.controlWidthPx
    val controlBottom = position.yPx + bounds.controlHeightPx

    return controlLeft < obstacle.rightPx &&
        controlRight > obstacle.leftPx &&
        controlTop < obstacle.bottomPx &&
        controlBottom > obstacle.topPx
}

/**
 * 障害物を避けるための一時退避位置を返す。
 *
 * 右端寄せを基本にしつつ、障害物の少し上に配置する。
 *
 * @param bounds 配置可能な境界情報
 * @param obstacle 一時回避領域
 * @param relocationGapPx 回避領域から離す距離
 * @return 一時退避用の表示位置
 */
internal fun relocatedTerminalFloatingControlPosition(
    bounds: TerminalFloatingControlBounds,
    obstacle: TerminalFloatingControlObstacle,
    relocationGapPx: Float,
): TerminalFloatingControlPosition =
    clampTerminalFloatingControlPosition(
        position =
            TerminalFloatingControlPosition(
                xPx = bounds.maxX(),
                yPx = obstacle.topPx - bounds.controlHeightPx - relocationGapPx,
            ),
        bounds = bounds,
    )

private fun TerminalFloatingControlBounds.minX(): Float = horizontalMarginPx

private fun TerminalFloatingControlBounds.maxX(): Float =
    max(
        minX(),
        containerWidthPx - horizontalMarginPx - controlWidthPx,
    )

private fun TerminalFloatingControlBounds.minY(): Float = topInsetPx + verticalMarginPx

private fun TerminalFloatingControlBounds.maxY(): Float =
    max(
        minY(),
        containerHeightPx - bottomInsetPx - verticalMarginPx - controlHeightPx,
    )

private fun TerminalFloatingControlBounds.createBottomObstacle(bottomObstacleHeightPx: Float): TerminalFloatingControlObstacle? {
    if (!isReady || bottomObstacleHeightPx <= 0f) {
        return null
    }

    val topPx = max(minY(), containerHeightPx - bottomObstacleHeightPx)
    return TerminalFloatingControlObstacle(
        leftPx = 0f,
        topPx = topPx,
        rightPx = containerWidthPx,
        bottomPx = containerHeightPx,
    )
}
