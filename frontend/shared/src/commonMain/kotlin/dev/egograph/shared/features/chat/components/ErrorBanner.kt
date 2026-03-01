package dev.egograph.shared.features.chat.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.features.chat.ChatErrorState

/**
 * エラーバナー コンポーネント
 *
 * チャット機能で発生したエラーを表示し、ユーザーに適切なアクションを提案します。
 *
 * @param errorState エラー状態
 * @param onRetry リトライ時のコールバック（省略可能）
 * @param onDismiss 閉じる際のコールバック
 * @param modifier 修飾子
 */
@Composable
fun ErrorBanner(
    errorState: ChatErrorState,
    onRetry: (() -> Unit)? = null,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val backgroundColor =
        when (errorState.severity) {
            dev.egograph.shared.core.domain.repository.ErrorSeverity.INFO -> MaterialTheme.colorScheme.primaryContainer
            dev.egograph.shared.core.domain.repository.ErrorSeverity.WARNING -> MaterialTheme.colorScheme.tertiaryContainer
            dev.egograph.shared.core.domain.repository.ErrorSeverity.ERROR -> MaterialTheme.colorScheme.errorContainer
            dev.egograph.shared.core.domain.repository.ErrorSeverity.CRITICAL -> MaterialTheme.colorScheme.error
        }

    val contentColor =
        when (errorState.severity) {
            dev.egograph.shared.core.domain.repository.ErrorSeverity.CRITICAL -> MaterialTheme.colorScheme.onError
            dev.egograph.shared.core.domain.repository.ErrorSeverity.ERROR -> MaterialTheme.colorScheme.onErrorContainer
            dev.egograph.shared.core.domain.repository.ErrorSeverity.WARNING -> MaterialTheme.colorScheme.onTertiaryContainer
            dev.egograph.shared.core.domain.repository.ErrorSeverity.INFO -> MaterialTheme.colorScheme.onPrimaryContainer
        }

    Surface(
        modifier = modifier.fillMaxWidth(),
        color = backgroundColor,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(dimens.space16),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = errorState.message,
                style = MaterialTheme.typography.bodyMedium,
                color = contentColor,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )

            if (errorState.isRetryable && onRetry != null) {
                Spacer(modifier = Modifier.width(dimens.space8))
                IconButton(onClick = onRetry) {
                    Icon(
                        imageVector = Icons.Default.Refresh,
                        contentDescription = "再試行",
                        tint = contentColor,
                    )
                }
            }

            IconButton(onClick = onDismiss) {
                Icon(
                    imageVector = Icons.Default.Close,
                    contentDescription = "閉じる",
                    tint = contentColor,
                )
            }
        }
    }
}
