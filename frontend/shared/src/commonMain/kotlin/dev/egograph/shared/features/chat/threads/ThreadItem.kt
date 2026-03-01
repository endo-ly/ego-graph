package dev.egograph.shared.features.chat.threads

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import dev.egograph.shared.core.domain.model.Thread
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.common.toCompactIsoDateTime
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * スレッドリストアイテムコンポーネント
 *
 * @param thread スレッド情報
 * @param isActive アクティブフラグ
 * @param onClick クリックコールバック
 * @param modifier Modifier
 */
@Composable
fun ThreadItem(
    thread: Thread,
    isActive: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes

    val backgroundColor =
        if (isActive) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.surface
        }

    val contentColor =
        if (isActive) {
            MaterialTheme.colorScheme.onPrimaryContainer
        } else {
            MaterialTheme.colorScheme.onSurface
        }

    val borderColor =
        if (isActive) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.outlineVariant
        }

    Column(
        modifier =
            modifier
                .testTagResourceId("thread_item")
                .fillMaxWidth()
                .clip(shapes.radiusSm)
                .background(backgroundColor)
                .border(
                    width = dimens.borderWidthThin,
                    color = borderColor,
                    shape = shapes.radiusSm,
                ).clickable(onClick = onClick)
                .padding(dimens.space12),
    ) {
        Text(
            text = thread.title,
            style = MaterialTheme.typography.bodyMedium,
            color = contentColor,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = thread.createdAt.toCompactIsoDateTime(),
            style = MaterialTheme.typography.bodySmall,
            color = contentColor.copy(alpha = 0.7f),
            modifier = Modifier.padding(top = dimens.space4),
        )
    }
}
