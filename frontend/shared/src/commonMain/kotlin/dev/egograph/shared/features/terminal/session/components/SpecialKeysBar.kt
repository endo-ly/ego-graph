package dev.egograph.shared.features.terminal.session.components

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * ターミナル用特殊キーボタンリスト
 *
 * Ctrl+C, Esc, 矢印キーなどの特殊キーを送信するボタン群。
 *
 * @param onKeyPress キー送信コールバック
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
    val dimens = EgoGraphThemeTokens.dimens
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

    Button(
        onClick = onClick,
        modifier = Modifier.testTagResourceId("terminal_voice_button"),
        colors =
            ButtonDefaults.buttonColors(
                containerColor = containerColor,
                contentColor = contentColor,
            ),
        contentPadding = ButtonDefaults.ButtonWithIconContentPadding,
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(dimens.space6)) {
            Icon(
                imageVector = if (isActive) Icons.Filled.Stop else Icons.Filled.Mic,
                contentDescription = if (isActive) "Stop voice input" else "Start voice input",
            )
            Text(
                text = if (isActive) "Listening" else "Mic",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
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
