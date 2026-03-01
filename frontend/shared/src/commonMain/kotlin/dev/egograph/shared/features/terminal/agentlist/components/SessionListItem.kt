package dev.egograph.shared.features.terminal.agentlist.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import dev.egograph.shared.core.domain.model.terminal.Session
import dev.egograph.shared.core.domain.model.terminal.SessionStatus
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.common.toCompactIsoDateTime
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.core.ui.theme.monospaceBody
import dev.egograph.shared.core.ui.theme.monospaceLabelSmall

/**
 * セッションリストアイテムコンポーネント
 *
 * @param session セッション情報
 * @param isActive アクティブフラグ
 * @param onClick クリックコールバック
 * @param modifier Modifier
 */
@Composable
fun SessionListItem(
    session: Session,
    isActive: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes
    val extendedColors = EgoGraphThemeTokens.extendedColors

    val backgroundColor = MaterialTheme.colorScheme.surface
    val contentColor = MaterialTheme.colorScheme.onSurface
    val borderColor = MaterialTheme.colorScheme.outlineVariant

    val statusColor =
        when (session.status) {
            SessionStatus.CONNECTED -> extendedColors.statusConnected
            SessionStatus.DISCONNECTED -> MaterialTheme.colorScheme.outline
            SessionStatus.FAILED -> MaterialTheme.colorScheme.error
        }

    Row(
        modifier =
            modifier
                .testTagResourceId("session_item")
                .fillMaxWidth()
                .clip(shapes.radiusXs)
                .background(backgroundColor)
                .border(
                    width = dimens.borderWidthThin,
                    color = borderColor,
                    shape = shapes.radiusXs,
                ).clickable(onClick = onClick)
                .padding(horizontal = dimens.space12, vertical = dimens.space10),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier =
                Modifier
                    .size(dimens.indicatorSizeMedium)
                    .clip(CircleShape)
                    .background(statusColor),
        )

        Spacer(modifier = Modifier.width(dimens.space10))

        Icon(
            imageVector = Icons.Default.Terminal,
            contentDescription = null,
            tint = contentColor.copy(alpha = 0.6f),
            modifier = Modifier.size(dimens.iconSizeMedium),
        )

        Column(
            modifier = Modifier.weight(1f).padding(start = dimens.space10),
        ) {
            Text(
                text = session.name,
                style = MaterialTheme.typography.monospaceBody,
                color = contentColor,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = "[${getStatusText(session.status)}]",
                style = MaterialTheme.typography.monospaceLabelSmall,
                color = if (session.status == SessionStatus.CONNECTED) extendedColors.statusConnected else contentColor.copy(alpha = 0.6f),
            )
        }

        Text(
            text = session.lastActivity.toCompactIsoDateTime(),
            style = MaterialTheme.typography.monospaceLabelSmall,
            color = contentColor.copy(alpha = 0.5f),
        )
    }
}

@Composable
private fun getStatusText(status: SessionStatus): String =
    when (status) {
        SessionStatus.CONNECTED -> "ONLINE"
        SessionStatus.DISCONNECTED -> "STANDBY"
        SessionStatus.FAILED -> "ERROR"
    }
