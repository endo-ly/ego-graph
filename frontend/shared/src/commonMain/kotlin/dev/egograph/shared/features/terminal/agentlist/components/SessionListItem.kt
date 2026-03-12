package dev.egograph.shared.features.terminal.agentlist.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.hoverable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import dev.egograph.shared.core.domain.model.terminal.Session
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.common.toCompactIsoDateTime
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.core.ui.theme.monospaceBody
import dev.egograph.shared.core.ui.theme.monospaceLabelSmall
import dev.egograph.shared.features.terminal.TerminalTestTags

internal fun previewDisplayLines(session: Session): List<String> =
    if (session.previewLines.isNotEmpty()) {
        session.previewLines
    } else {
        listOf("Preview unavailable")
    }

internal fun sessionSubtitle(session: Session): String? = session.name.takeUnless { it.isBlank() || it == session.sessionId }

/**
 * セッションリストアイテムコンポーネント
 *
 * @param session セッション情報
 * @param onClick クリックコールバック
 * @param modifier Modifier
 */
@Composable
fun SessionListItem(
    session: Session,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes
    val extendedColors = EgoGraphThemeTokens.extendedColors
    val previewLines = previewDisplayLines(session)
    val subtitle = sessionSubtitle(session)
    val previewScrollState = rememberScrollState()
    val interactionSource = remember { MutableInteractionSource() }
    val isHovered by interactionSource.collectIsHoveredAsState()
    val pulse = rememberInfiniteTransition(label = "sessionIndicatorPulse")
    val pulseAlpha =
        pulse.animateFloat(
            initialValue = 0.45f,
            targetValue = 1f,
            animationSpec = infiniteRepeatable(animation = tween(1300), repeatMode = RepeatMode.Reverse),
            label = "sessionIndicatorAlpha",
        )

    Column(
        modifier =
            modifier
                .testTagResourceId(TerminalTestTags.SESSION_ITEM)
                .fillMaxWidth()
                .clip(shapes.radiusLg)
                .background(if (isHovered) Color(0xFF1C1C1F) else Color(0xFF141416))
                .border(
                    width = dimens.borderWidthThin,
                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.45f),
                    shape = shapes.radiusLg,
                ).hoverable(interactionSource)
                .clickable(onClick = onClick)
                .padding(horizontal = dimens.space16, vertical = dimens.space16),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Top,
        ) {
            Box(
                modifier =
                    Modifier
                        .padding(top = dimens.space6)
                        .size(dimens.indicatorSizeMedium)
                        .alpha(pulseAlpha.value)
                        .clip(CircleShape)
                        .background(extendedColors.success),
            )
            Spacer(modifier = Modifier.width(dimens.space12))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = session.sessionId,
                    style = MaterialTheme.typography.monospaceBody,
                    color = if (isHovered) extendedColors.success else MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                subtitle?.let {
                    Spacer(modifier = Modifier.height(dimens.space4))
                    Text(
                        text = it,
                        style = MaterialTheme.typography.monospaceLabelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Spacer(modifier = Modifier.width(dimens.space12))
            Text(
                text = session.lastActivity.toCompactIsoDateTime(),
                style = MaterialTheme.typography.monospaceLabelSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.45f),
            )
        }

        Spacer(modifier = Modifier.height(dimens.space12))

        Box(
            modifier =
                Modifier
                    .testTagResourceId(TerminalTestTags.SESSION_PREVIEW)
                    .fillMaxWidth()
                    .heightIn(max = dimens.size160)
                    .clip(shapes.radiusMd)
                    .background(Color(0xFF050505))
                    .border(
                        width = dimens.borderWidthThin,
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.2f),
                        shape = shapes.radiusMd,
                    ).padding(start = dimens.space12, end = dimens.space12, top = dimens.space12, bottom = dimens.space10),
        ) {
            Box(
                modifier =
                    Modifier
                        .align(Alignment.CenterStart)
                        .clip(shapes.radiusSm)
                        .background(
                            if (isHovered) {
                                extendedColors.success.copy(alpha = 0.5f)
                            } else {
                                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.65f)
                            },
                        ).width(dimens.space4)
                        .height(dimens.size160 / 4),
            )
            Column(
                modifier =
                    Modifier
                        .padding(start = dimens.space8)
                        .verticalScroll(previewScrollState),
            ) {
                previewLines.forEach { line ->
                    Text(
                        text = line,
                        style = MaterialTheme.typography.monospaceLabelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (line != previewLines.last()) {
                        Spacer(modifier = Modifier.height(dimens.space4))
                    }
                }
            }
        }
    }
}
