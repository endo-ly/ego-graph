package dev.egograph.shared.core.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import dev.egograph.shared.core.ui.common.testTagResourceId

/**
 * 音声入力の開始/停止を切り替えるアイコンボタン。
 *
 * @param isActive 音声入力がアクティブな状態かどうか
 * @param onClick ボタンタップ時の処理
 * @param modifier 追加のModifier
 * @param testTag UIテスト用タグ
 * @param startContentDescription 音声入力開始時のコンテンツ説明
 * @param stopContentDescription 音声入力停止時のコンテンツ説明
 */
@Composable
fun VoiceInputToggleButton(
    isActive: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    testTag: String = "voice_input_button",
    startContentDescription: String = "Start voice input",
    stopContentDescription: String = "Stop voice input",
) {
    val containerColor =
        if (isActive) {
            MaterialTheme.colorScheme.errorContainer
        } else {
            MaterialTheme.colorScheme.surfaceVariant
        }
    val contentColor =
        if (isActive) {
            MaterialTheme.colorScheme.onErrorContainer
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        }

    FilledIconButton(
        onClick = onClick,
        modifier = modifier.testTagResourceId(testTag),
        colors =
            IconButtonDefaults.filledIconButtonColors(
                containerColor = containerColor,
                contentColor = contentColor,
            ),
    ) {
        Icon(
            imageVector = if (isActive) Icons.Filled.Stop else Icons.Filled.Mic,
            contentDescription = if (isActive) stopContentDescription else startContentDescription,
        )
    }
}
