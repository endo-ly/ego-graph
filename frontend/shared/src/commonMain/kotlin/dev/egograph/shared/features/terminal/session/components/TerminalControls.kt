package dev.egograph.shared.features.terminal.session.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.features.terminal.TerminalTestTags

@Composable
fun TerminalBackButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    IconButton(
        onClick = onClick,
        modifier = modifier.testTagResourceId(TerminalTestTags.TERMINAL_BACK_BUTTON),
    ) {
        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
    }
}

@Composable
fun TerminalKeyboardToggleButton(
    isVisible: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    IconButton(
        onClick = onClick,
        modifier = modifier.testTagResourceId(TerminalTestTags.TERMINAL_KEYBOARD_TOGGLE),
    ) {
        Icon(
            imageVector = if (isVisible) Icons.Default.KeyboardArrowDown else Icons.Default.KeyboardArrowUp,
            contentDescription = if (isVisible) "Hide keyboard" else "Show keyboard",
        )
    }
}

@Composable
fun TerminalCopyButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    IconButton(
        onClick = onClick,
        modifier = modifier.testTagResourceId(TerminalTestTags.TERMINAL_COPY_BUTTON),
    ) {
        Icon(Icons.Default.ContentCopy, contentDescription = "Copy terminal text")
    }
}

@Composable
fun TerminalFloatingControlPill(
    sessionId: String,
    isConnected: Boolean,
    isKeyboardVisible: Boolean,
    onBack: () -> Unit,
    onKeyboardToggle: () -> Unit,
    onCopy: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes
    val indicatorColor = if (isConnected) EgoGraphThemeTokens.extendedColors.success else MaterialTheme.colorScheme.error

    Surface(
        modifier = modifier.testTagResourceId(TerminalTestTags.TERMINAL_STATUS_PILL),
        color = Color(0xD91A1A1C),
        contentColor = MaterialTheme.colorScheme.onSurface,
        shape = shapes.radiusXl,
        tonalElevation = dimens.space8,
        shadowElevation = dimens.space8,
    ) {
        Row(
            modifier =
                Modifier.padding(horizontal = dimens.space8, vertical = dimens.space6),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TerminalBackButton(onClick = onBack)
            Spacer(modifier = Modifier.width(dimens.space8))
            Row(
                modifier = Modifier.widthIn(max = 180.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier =
                        Modifier
                            .size(dimens.indicatorSizeSmall)
                            .clip(CircleShape)
                            .background(indicatorColor),
                )
                Spacer(modifier = Modifier.width(dimens.space8))
                Text(
                    text = sessionId,
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(modifier = Modifier.width(dimens.space8))
            TerminalKeyboardToggleButton(isVisible = isKeyboardVisible, onClick = onKeyboardToggle)
            TerminalCopyButton(onClick = onCopy)
        }
    }
}

@Composable
fun TerminalCopyFeedback(
    message: String,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes

    Box(
        modifier =
            modifier
                .testTagResourceId(TerminalTestTags.TERMINAL_COPY_FEEDBACK)
                .clip(shapes.radiusMd)
                .background(MaterialTheme.colorScheme.onSurface.copy(alpha = 0.92f))
                .padding(horizontal = dimens.space12, vertical = dimens.space8),
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.surface,
        )
    }
}
