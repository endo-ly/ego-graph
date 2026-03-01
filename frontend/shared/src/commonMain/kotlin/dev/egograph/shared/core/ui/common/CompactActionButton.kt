package dev.egograph.shared.core.ui.common

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * コンパクト表示用の共通アクションボタン。
 */
@Composable
internal fun CompactActionButton(
    onClick: () -> Unit,
    icon: ImageVector,
    contentDescription: String?,
    testTag: String,
    text: String? = null,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes
    val buttonHeight = dimens.space28
    val buttonPadding = PaddingValues(horizontal = dimens.space8)
    val iconSize = dimens.iconSizeSmall
    val minWidth = if (text == null) dimens.space48 else dimens.space60

    OutlinedButton(
        onClick = onClick,
        shape = shapes.radiusXs,
        contentPadding = buttonPadding,
        modifier =
            Modifier
                .testTagResourceId(testTag)
                .height(buttonHeight)
                .widthIn(min = minWidth),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = contentDescription,
            modifier = Modifier.size(iconSize),
        )
        if (text != null) {
            Spacer(modifier = Modifier.width(dimens.space4))
            Text(text)
        }
    }
}
