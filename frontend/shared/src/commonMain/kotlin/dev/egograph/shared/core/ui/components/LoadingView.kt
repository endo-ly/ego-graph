package dev.egograph.shared.core.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * ローディング表示コンポーネント
 *
 * @param modifier Modifier
 * @param message ローディングメッセージ
 * @param height 表示領域の高さ
 */
@Composable
fun LoadingView(
    modifier: Modifier = Modifier,
    message: String = "Loading...",
    height: Dp? = null,
) {
    val resolvedHeight = height ?: EgoGraphThemeTokens.dimens.listLoadingHeight

    Box(
        modifier =
            modifier
                .fillMaxWidth()
                .height(resolvedHeight),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
