package dev.egograph.shared.features.terminal.agentlist.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import dev.egograph.shared.core.domain.model.terminal.Session
import dev.egograph.shared.core.domain.model.terminal.SessionStatus
import dev.egograph.shared.core.ui.common.ListStateContent
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.core.ui.theme.monospaceBodyMedium
import dev.egograph.shared.core.ui.theme.monospaceLabelSmall

/**
 * ターミナルセッション一覧コンポーネント
 *
 * @param sessions セッション一覧
 * @param selectedSessionId 選択中のセッションID
 * @param isLoading 読み込み中フラグ
 * @param error エラーメッセージ
 * @param onSessionClick セッション選択コールバック
 * @param onRefresh 更新コールバック
 * @param onOpenGatewaySettings Gateway設定を開くコールバック
 * @param modifier Modifier
 */
@Composable
fun SessionList(
    sessions: List<Session>,
    selectedSessionId: String?,
    isLoading: Boolean,
    error: String?,
    onSessionClick: (String) -> Unit,
    onRefresh: () -> Unit,
    onOpenGatewaySettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes
    val extendedColors = EgoGraphThemeTokens.extendedColors
    val activeSessionCount = sessions.count { it.status == SessionStatus.CONNECTED }

    Column(
        modifier =
            modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .statusBarsPadding(),
    ) {
        Column(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = dimens.space16, vertical = dimens.space12),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier =
                        Modifier
                            .size(dimens.indicatorSizeSmall)
                            .background(
                                color = if (activeSessionCount > 0) extendedColors.statusConnected else MaterialTheme.colorScheme.outline,
                                shape = shapes.statusCircle,
                            ),
                )
                Spacer(modifier = Modifier.width(dimens.space8))

                Icon(
                    imageVector = Icons.Default.Terminal,
                    contentDescription = null,
                    modifier = Modifier.size(dimens.iconSizeMedium),
                    tint = MaterialTheme.colorScheme.primary,
                )
                Spacer(modifier = Modifier.width(dimens.space8))

                Text(
                    text = "TERMINAL SESSIONS",
                    style =
                        MaterialTheme.typography.monospaceBodyMedium.copy(
                            fontWeight = FontWeight.Bold,
                        ),
                    color = MaterialTheme.colorScheme.onSurface,
                )

                Spacer(modifier = Modifier.weight(1f))

                OutlinedButton(
                    onClick = onRefresh,
                    enabled = !isLoading,
                    shape = shapes.radiusXs,
                    contentPadding = PaddingValues(horizontal = dimens.space8),
                    modifier = Modifier.height(dimens.space28).widthIn(min = dimens.space48),
                ) {
                    Icon(
                        imageVector = Icons.Default.Refresh,
                        contentDescription = "Sync",
                        modifier = Modifier.size(dimens.iconSizeSmall),
                    )
                }

                Spacer(modifier = Modifier.width(dimens.space6))

                OutlinedButton(
                    onClick = onOpenGatewaySettings,
                    shape = shapes.radiusXs,
                    contentPadding = PaddingValues(horizontal = dimens.space8),
                    modifier = Modifier.height(dimens.space28).widthIn(min = dimens.space48),
                ) {
                    Icon(
                        imageVector = Icons.Default.Settings,
                        contentDescription = "Settings",
                        modifier = Modifier.size(dimens.iconSizeSmall),
                    )
                }
            }

            Spacer(modifier = Modifier.height(dimens.space8))

            Text(
                text = "$activeSessionCount ACTIVE",
                style =
                    MaterialTheme.typography.monospaceLabelSmall.copy(fontWeight = FontWeight.Medium),
                color = if (activeSessionCount > 0) extendedColors.statusConnected else MaterialTheme.colorScheme.outline,
                modifier = Modifier.align(Alignment.End),
            )
        }

        ListStateContent(
            items = sessions,
            isLoading = isLoading,
            errorMessage = error,
            modifier = Modifier.fillMaxSize(),
            loading = { containerModifier ->
                SessionListLoading(modifier = containerModifier)
            },
            empty = { containerModifier ->
                SessionListEmpty(modifier = containerModifier)
            },
            error = { message, containerModifier ->
                SessionListError(
                    error = message,
                    onRefresh = onRefresh,
                    modifier = containerModifier,
                )
            },
            content = { items, containerModifier ->
                SessionListContent(
                    sessions = items,
                    selectedSessionId = selectedSessionId,
                    onSessionClick = onSessionClick,
                    modifier = containerModifier,
                )
            },
        )
    }
}

@Composable
private fun SessionListContent(
    sessions: List<Session>,
    selectedSessionId: String?,
    onSessionClick: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val listState = rememberLazyListState()
    LazyColumn(
        modifier = modifier.padding(vertical = dimens.space8),
        state = listState,
        verticalArrangement = Arrangement.spacedBy(dimens.space8),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        items(
            items = sessions,
            key = { it.sessionId },
        ) { session ->
            SessionListItem(
                session = session,
                isActive = session.sessionId == selectedSessionId,
                onClick = { onSessionClick(session.sessionId) },
                modifier = Modifier.fillMaxWidth().padding(horizontal = dimens.space16),
            )
        }
        item {
            Spacer(modifier = Modifier.height(dimens.space16))
        }
    }
}
