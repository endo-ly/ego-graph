package dev.egograph.shared.features.sidebar

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.outlined.Computer
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import dev.egograph.shared.core.ui.common.CompactActionButton
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * サイドバーのヘッダーコンポーネント
 *
 * 新しいチャット、設定、ターミナルへのボタンを含むヘッダー。
 *
 * @param onNewChatClick 新規チャットボタンクリックコールバック
 * @param onSettingsClick 設定ボタンクリックコールバック
 * @param onTerminalClick ターミナルボタンクリックコールバック
 */
@Composable
fun SidebarHeader(
    onNewChatClick: () -> Unit,
    onSettingsClick: () -> Unit = {},
    onTerminalClick: () -> Unit = {},
) {
    val dimens = EgoGraphThemeTokens.dimens

    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(dimens.space16),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "History",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.weight(1f))

        CompactActionButton(
            onClick = onSettingsClick,
            icon = Icons.Default.Settings,
            contentDescription = "Settings",
            testTag = "settings_button",
        )

        Spacer(modifier = Modifier.width(dimens.space8))

        CompactActionButton(
            onClick = onTerminalClick,
            icon = Icons.Outlined.Computer,
            contentDescription = "Terminal",
            testTag = "terminal_button",
        )

        Spacer(modifier = Modifier.width(dimens.space8))

        CompactActionButton(
            onClick = onNewChatClick,
            icon = Icons.Default.Add,
            contentDescription = null,
            text = "New",
            testTag = "new_chat_button",
        )
    }
}
