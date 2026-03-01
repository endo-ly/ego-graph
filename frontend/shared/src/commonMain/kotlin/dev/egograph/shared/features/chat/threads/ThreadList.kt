package dev.egograph.shared.features.chat.threads

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import dev.egograph.shared.core.domain.model.Thread
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.components.EmptyView
import dev.egograph.shared.core.ui.components.ErrorView
import dev.egograph.shared.core.ui.components.LoadingView
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * スレッド一覧コンポーネント
 *
 * チャットスレッドの一覧を表示する。Pull-to-refreshと無限スクロールをサポート。
 *
 * @param threads スレッド一覧
 * @param selectedThreadId 選択中のスレッドID
 * @param isLoading 読み込み中フラグ
 * @param isLoadingMore 追加読み込み中フラグ
 * @param hasMore さらに項目があるかどうか
 * @param error エラーメッセージ
 * @param onThreadClick スレッド選択コールバック
 * @param onRefresh 更新コールバック
 * @param onLoadMore 追加読み込みコールバック
 * @param modifier Modifier
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ThreadList(
    threads: List<Thread>,
    selectedThreadId: String?,
    isLoading: Boolean,
    isLoadingMore: Boolean,
    hasMore: Boolean,
    error: String?,
    onThreadClick: (String) -> Unit,
    onRefresh: () -> Unit,
    onLoadMore: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val pullRefreshState = rememberPullToRefreshState()
    val listState = rememberLazyListState()

    InfiniteScrollEffect(
        listState = listState,
        itemCount = threads.size,
        isLoading = isLoading,
        isLoadingMore = isLoadingMore,
        hasMore = hasMore,
        error = error,
        onLoadMore = onLoadMore,
    )

    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (isLoading && threads.isEmpty()) {
            LoadingView()
        } else {
            PullToRefreshBox(
                isRefreshing = isLoading,
                onRefresh = onRefresh,
                state = pullRefreshState,
                modifier = Modifier.fillMaxSize(),
            ) {
                ThreadListContent(
                    threads = threads,
                    selectedThreadId = selectedThreadId,
                    isLoadingMore = isLoadingMore,
                    error = error,
                    listState = listState,
                    onThreadClick = onThreadClick,
                )
            }
        }
    }
}

@Composable
private fun ThreadListContent(
    threads: List<Thread>,
    selectedThreadId: String?,
    isLoadingMore: Boolean,
    error: String?,
    listState: LazyListState,
    onThreadClick: (String) -> Unit,
) {
    val dimens = EgoGraphThemeTokens.dimens

    if (error != null && threads.isEmpty()) {
        Box(
            modifier =
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState()),
        ) {
            ErrorView(message = error)
        }
    } else if (threads.isEmpty()) {
        Box(
            modifier =
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState()),
        ) {
            EmptyView(message = "No threads found")
        }
    } else {
        LazyColumn(
            state = listState,
            contentPadding = PaddingValues(dimens.space16),
            verticalArrangement = Arrangement.spacedBy(dimens.space8),
            modifier =
                Modifier
                    .testTagResourceId("thread_list")
                    .fillMaxSize(),
        ) {
            items(
                items = threads,
                key = { it.threadId },
            ) { thread ->
                ThreadItem(
                    thread = thread,
                    isActive = thread.threadId == selectedThreadId,
                    onClick = { onThreadClick(thread.threadId) },
                )
            }

            if (isLoadingMore) {
                item {
                    LoadingMoreIndicator()
                }
            }
        }
    }
}

@Composable
private fun LoadingMoreIndicator() {
    val dimens = EgoGraphThemeTokens.dimens

    Box(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(dimens.space12),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator()
    }
}

@Composable
private fun InfiniteScrollEffect(
    listState: LazyListState,
    itemCount: Int,
    isLoading: Boolean,
    isLoadingMore: Boolean,
    hasMore: Boolean,
    error: String?,
    onLoadMore: () -> Unit,
) {
    var lastRequestedSize by remember { mutableIntStateOf(0) }
    val lastVisibleIndex by remember {
        derivedStateOf {
            listState.layoutInfo.visibleItemsInfo
                .lastOrNull()
                ?.index
        }
    }

    LaunchedEffect(error) {
        if (error != null) {
            lastRequestedSize = 0
        }
    }

    LaunchedEffect(lastVisibleIndex, itemCount, isLoading, isLoadingMore, hasMore) {
        val lastIndex = lastVisibleIndex
        if (
            lastIndex != null &&
            itemCount > 0 &&
            lastIndex >= itemCount - 4 &&
            hasMore &&
            !isLoading &&
            !isLoadingMore &&
            itemCount != lastRequestedSize
        ) {
            lastRequestedSize = itemCount
            onLoadMore()
        }
    }
}
