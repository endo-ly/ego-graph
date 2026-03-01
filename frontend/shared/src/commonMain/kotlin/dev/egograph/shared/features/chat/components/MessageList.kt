package dev.egograph.shared.features.chat.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import dev.egograph.shared.core.domain.model.ThreadMessage
import dev.egograph.shared.core.ui.common.ListStateContent
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.filter

/**
 * メッセージ一覧コンポーネント
 *
 * チャットのメッセージリストを表示する。スクロール時にキーボードを非表示にする。
 *
 * @param messages メッセージ一覧
 * @param modifier Modifier
 * @param isLoading 読み込み中フラグ
 * @param errorMessage エラーメッセージ
 * @param streamingMessageId ストリーミング中のメッセージID
 * @param activeAssistantTask アクティブなアシスタントタスク
 */
@Composable
fun MessageList(
    messages: List<ThreadMessage>,
    modifier: Modifier = Modifier,
    isLoading: Boolean = false,
    errorMessage: String? = null,
    streamingMessageId: String? = null,
    activeAssistantTask: String? = null,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val listState = rememberLazyListState()
    val reversedMessages = remember(messages) { messages.asReversed() }
    val keyboardController = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current

    LaunchedEffect(listState) {
        snapshotFlow { listState.isScrollInProgress }
            .filter { it }
            .collectLatest {
                keyboardController?.hide()
                focusManager.clearFocus()
            }
    }

    ListStateContent(
        items = messages,
        isLoading = isLoading,
        errorMessage = errorMessage,
        modifier = modifier.fillMaxSize(),
        loading = { containerModifier ->
            Box(modifier = containerModifier, contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = MaterialTheme.colorScheme.secondary)
            }
        },
        empty = { containerModifier ->
            Box(modifier = containerModifier, contentAlignment = Alignment.Center) {
                MessageListEmpty()
            }
        },
        error = { message, containerModifier ->
            Box(modifier = containerModifier, contentAlignment = Alignment.Center) {
                Text(
                    text = message,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.testTagResourceId("error_message"),
                )
            }
        },
        content = { _, containerModifier ->
            LazyColumn(
                state = listState,
                reverseLayout = true,
                modifier =
                    containerModifier
                        .testTagResourceId("message_list"),
                contentPadding = PaddingValues(vertical = dimens.space16),
            ) {
                if (isLoading) {
                    item {
                        Box(
                            modifier =
                                Modifier
                                    .fillMaxWidth()
                                    .padding(dimens.space16),
                            contentAlignment = Alignment.Center,
                        ) {
                            CircularProgressIndicator(
                                color = MaterialTheme.colorScheme.secondary,
                                modifier = Modifier.padding(dimens.space8),
                            )
                        }
                    }
                }

                items(
                    items = reversedMessages,
                    key = { it.messageId },
                ) { message ->
                    ChatMessage(
                        message = message,
                        isStreaming = message.messageId == streamingMessageId,
                        activeAssistantTask = activeAssistantTask,
                    )
                }
            }
        },
    )
}

/**
 * メッセージ一覧が空の場合の表示
 *
 * @param modifier Modifier
 */
@Composable
fun MessageListEmpty(modifier: Modifier = Modifier) {
    val dimens = EgoGraphThemeTokens.dimens

    Box(
        modifier =
            modifier
                .fillMaxWidth()
                .padding(dimens.space32),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "No messages yet",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
