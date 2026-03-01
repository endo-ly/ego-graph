package dev.egograph.shared.features.terminal.session.components

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.components.VoiceInputToggleButton
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * ターミナル用特殊キーボタンリスト
 *
 * Ctrl+C, Esc, 矢印キーなどの特殊キーを送信するボタン群。
 *
 * @param onKeyPress キー送信コールバック
 * @param onVoiceInputClick 音声入力ボタン押下時のコールバック
 * @param isVoiceInputActive 音声入力が有効かどうか
 * @param modifier Modifier
 */
@Composable
fun SpecialKeysBar(
    onKeyPress: (String) -> Unit,
    onVoiceInputClick: () -> Unit,
    isVoiceInputActive: Boolean,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val scrollState = rememberScrollState()

    Row(
        modifier =
            modifier
                .testTagResourceId("special_keys_bar")
                .fillMaxWidth()
                .horizontalScroll(scrollState),
    ) {
        VoiceInputButton(
            isActive = isVoiceInputActive,
            onClick = onVoiceInputClick,
        )
        SpecialKeyButton("/", "/", onKeyPress)
        SpecialKeyButton("↑", "\u001B[A", onKeyPress)
        SpecialKeyButton("↓", "\u001B[B", onKeyPress)
        SpecialKeyButton("←", "\u001B[D", onKeyPress)
        SpecialKeyButton("→", "\u001B[C", onKeyPress)
        Spacer(modifier = Modifier.width(dimens.space8))

        SpecialKeyButton("Ctrl+C", "\u0003", onKeyPress)
        SpecialKeyButton("Esc", "\u001B", onKeyPress)
        SpecialKeyButton("Tab", "\t", onKeyPress)
        SpecialKeyButton("Shift+Tab", "\u001B[Z", onKeyPress)
        Spacer(modifier = Modifier.width(dimens.space8))

        SpecialKeyButton("Ctrl", "\u0000", onKeyPress)
        SpecialKeyButton("Ctrl+D", "\u0004", onKeyPress)
    }
}

@Composable
private fun VoiceInputButton(
    isActive: Boolean,
    onClick: () -> Unit,
) {
    VoiceInputToggleButton(
        isActive = isActive,
        onClick = onClick,
        testTag = "terminal_voice_button",
    )
}

@Composable
private fun SpecialKeyButton(
    label: String,
    keySequence: String,
    onKeyPress: (String) -> Unit,
) {
    Button(
        onClick = { onKeyPress(keySequence) },
        colors =
            ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
            ),
        contentPadding = ButtonDefaults.ButtonWithIconContentPadding,
    ) {
        Text(label, style = MaterialTheme.typography.bodySmall)
    }
}
