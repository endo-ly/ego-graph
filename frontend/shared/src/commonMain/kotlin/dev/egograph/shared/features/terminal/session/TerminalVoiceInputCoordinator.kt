package dev.egograph.shared.features.terminal.session

import androidx.compose.runtime.Composable
import dev.egograph.shared.core.ui.components.rememberVoiceInputCoordinator

/**
 * ターミナル画面向け音声入力コーディネーター。
 *
 * @property isActive 音声入力が有効かどうか
 * @property onToggle 音声入力の開始/停止を切り替える処理
 */
internal data class TerminalVoiceInputCoordinator(
    val isActive: Boolean,
    val onToggle: () -> Unit,
)

/**
 * 共通音声入力コーディネーターをターミナル向け型に変換して返す。
 *
 * @param onRecognizedText 認識した確定テキストを受け取るコールバック
 * @param onError 音声入力中のエラー通知コールバック
 */
@Composable
internal fun rememberTerminalVoiceInputCoordinator(
    onRecognizedText: (String) -> Unit,
    onError: (String) -> Unit,
): TerminalVoiceInputCoordinator {
    val coordinator =
        rememberVoiceInputCoordinator(
            onRecognizedText = onRecognizedText,
            onError = onError,
        )

    return TerminalVoiceInputCoordinator(
        isActive = coordinator.isActive,
        onToggle = coordinator.onToggle,
    )
}
