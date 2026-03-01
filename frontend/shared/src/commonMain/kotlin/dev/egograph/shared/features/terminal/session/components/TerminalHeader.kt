package dev.egograph.shared.features.terminal.session.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.core.ui.theme.monospaceBody
import dev.egograph.shared.core.ui.theme.monospaceBodyMedium

/**
 * ターミナル画面のヘッダー
 *
 * エージェントID、接続状態、戻るボタンを含む。
 *
 * @param agentId エージェントID
 * @param isLoading 接続中フラグ
 * @param error エラーメッセージ（nullの場合は正常）
 * @param onBack 戻るボタンコールバック
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TerminalHeader(
    agentId: String,
    isLoading: Boolean,
    error: String?,
    onBack: () -> Unit,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes
    val extendedColors = EgoGraphThemeTokens.extendedColors

    CenterAlignedTopAppBar(
        title = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center,
            ) {
                when {
                    isLoading -> {
                        Text(
                            text = "CONNECTING...",
                            style = MaterialTheme.typography.monospaceBodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    error == null -> {
                        Text(
                            text = agentId,
                            style = MaterialTheme.typography.monospaceBodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Spacer(modifier = Modifier.width(dimens.space8))
                        Box(
                            modifier =
                                Modifier
                                    .size(dimens.indicatorSizeSmall)
                                    .clip(shapes.statusCircle)
                                    .background(extendedColors.statusConnected)
                                    .semantics {
                                        contentDescription = "Connected"
                                    },
                        )
                    }
                    else -> {
                        Text(
                            text = agentId,
                            style = MaterialTheme.typography.monospaceBody,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Spacer(modifier = Modifier.width(dimens.space8))
                        Box(
                            modifier =
                                Modifier
                                    .size(dimens.indicatorSizeSmall)
                                    .clip(shapes.statusCircle)
                                    .background(MaterialTheme.colorScheme.error)
                                    .semantics {
                                        contentDescription = "Disconnected"
                                    },
                        )
                    }
                }
            }
        },
        modifier = Modifier.height(dimens.terminalHeaderHeight),
        navigationIcon = {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back to list")
            }
        },
    )
}
