package dev.egograph.shared.features.chat.threads

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

@Composable
fun ThreadListLoading(
    modifier: Modifier = Modifier,
    message: String = "Loading...",
) {
    val dimens = EgoGraphThemeTokens.dimens

    Box(
        modifier =
            modifier
                .fillMaxWidth()
                .height(dimens.listLoadingHeight),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
