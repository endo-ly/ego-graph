package dev.egograph.shared.features.sidebar

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Computer
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

@Composable
fun SidebarFooter(
    onNewChatClick: () -> Unit,
    onSettingsClick: () -> Unit,
    onTerminalClick: () -> Unit,
    onSystemPromptClick: () -> Unit,
) {
    val dimens = EgoGraphThemeTokens.dimens

    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(horizontal = dimens.space16, vertical = dimens.space8),
        horizontalArrangement = Arrangement.spacedBy(dimens.space8),
    ) {
        FooterIconButton(
            icon = Icons.Outlined.Settings,
            onClick = onSettingsClick,
            contentDescription = "Settings",
            testTag = "settings_button",
            modifier = Modifier.weight(1f),
        )

        FooterIconButton(
            icon = Icons.Outlined.Tune,
            onClick = onSystemPromptClick,
            contentDescription = "System prompt",
            testTag = "system_prompt_button",
            modifier = Modifier.weight(1f),
        )

        FooterIconButton(
            icon = Icons.Outlined.Computer,
            onClick = onTerminalClick,
            contentDescription = "Terminal",
            testTag = "terminal_button",
            modifier = Modifier.weight(1f),
        )

        FooterIconWithLabelButton(
            icon = Icons.Outlined.Add,
            label = "New",
            onClick = onNewChatClick,
            testTag = "new_chat_button",
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun FooterIconButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
    contentDescription: String,
    testTag: String,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes

    Surface(
        onClick = onClick,
        shape = shapes.statusCircle,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        border = BorderStroke(dimens.borderWidthThin, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f)),
        tonalElevation = dimens.zero,
        shadowElevation = dimens.zero,
        modifier =
            modifier
                .height(dimens.space36)
                .testTagResourceId(testTag),
    ) {
        Box(
            modifier = Modifier.size(dimens.space36),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = contentDescription,
                modifier = Modifier.size(dimens.iconSize18),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun FooterIconWithLabelButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
    testTag: String,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes

    Surface(
        onClick = onClick,
        shape = shapes.radiusLg,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        border = BorderStroke(dimens.borderWidthThin, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f)),
        tonalElevation = dimens.zero,
        shadowElevation = dimens.zero,
        modifier =
            modifier
                .height(dimens.space36)
                .testTagResourceId(testTag),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = dimens.space12),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(dimens.iconSizeSmall),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.width(dimens.space4))
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
