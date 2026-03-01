package dev.egograph.shared.features.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.outlined.Computer
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.koin.koinScreenModel
import co.touchlab.kermit.Logger
import dev.egograph.shared.core.ui.common.CompactActionButton
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.features.chat.components.ChatComposer
import dev.egograph.shared.features.chat.components.ErrorBanner
import dev.egograph.shared.features.chat.components.MessageList
import kotlinx.serialization.Transient

/**
 * チャット画面
 *
 * メッセージ一覧表示、入力、ストリーミング応答を処理するメイン画面。
 */
class ChatScreen(
    @Transient private val onOpenSidebar: () -> Unit = {},
    @Transient private val onOpenTerminal: () -> Unit = {},
    @Transient private val onNewChat: () -> Unit = {},
) : Screen {
    @Composable
    override fun Content() {
        val dimens = EgoGraphThemeTokens.dimens
        val screenModel = koinScreenModel<ChatScreenModel>()
        val state by screenModel.state.collectAsState()
        val snackbarHostState = remember { SnackbarHostState() }

        // Effect の収集
        LaunchedEffect(Unit) {
            screenModel.effect.collect { effect ->
                when (effect) {
                    is ChatEffect.ShowMessage -> {
                        snackbarHostState.showSnackbar(effect.message)
                    }
                    is ChatEffect.ShowError -> {
                        // エラー状態は既にStateに設定されているので、
                        // ここではログ記録のみ（EffectはOne-shotイベントの通知）
                        Logger.w { "Error occurred: ${effect.errorState.message}" }
                    }
                    is ChatEffect.NavigateToThread -> {
                        Logger.w { "NavigateToThread effect received but navigation not implemented yet" }
                    }
                }
            }
        }

        Scaffold(
            modifier = Modifier.fillMaxSize(),
            contentWindowInsets = WindowInsets(0, 0, 0, 0),
            snackbarHost = { SnackbarHost(snackbarHostState) },
            bottomBar = {
                ChatComposer(
                    models = state.composer.models,
                    selectedModelId = state.composer.selectedModelId,
                    isLoadingModels = state.composer.isLoadingModels,
                    modelsError = state.composer.modelsError,
                    onModelSelected = screenModel::selectModel,
                    onSendMessage = { text ->
                        screenModel.sendMessage(text)
                    },
                    isLoading = state.composer.isSending,
                    modifier =
                        Modifier
                            .navigationBarsPadding()
                            .imePadding(),
                )
            },
        ) { paddingValues ->
            Column(
                modifier =
                    Modifier
                        .fillMaxSize()
                        .padding(paddingValues),
            ) {
                ChatTopActions(
                    onOpenSidebar = onOpenSidebar,
                    onOpenTerminal = onOpenTerminal,
                    onNewChat = onNewChat,
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .statusBarsPadding()
                            .padding(horizontal = dimens.space8, vertical = dimens.space2),
                )

                // エラーバナー（エラーがある場合のみ表示）
                state.chatError?.let { errorState ->
                    ErrorBanner(
                        errorState = errorState,
                        onRetry = { screenModel.retryLastMessage() },
                        onDismiss = { screenModel.clearChatError() },
                    )
                }

                MessageList(
                    messages = state.messageList.messages,
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .weight(1f),
                    isLoading = state.messageList.isLoading,
                    errorMessage = state.messageList.error,
                    streamingMessageId = state.messageList.streamingMessageId,
                    activeAssistantTask = state.messageList.activeAssistantTask,
                )
            }
        }
    }
}

@Composable
private fun ChatTopActions(
    onOpenSidebar: () -> Unit,
    onOpenTerminal: () -> Unit,
    onNewChat: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens

    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(
            onClick = onOpenSidebar,
            modifier = Modifier.testTagResourceId("chat_sidebar_button"),
        ) {
            Icon(
                imageVector = Icons.Default.Menu,
                contentDescription = "Open sidebar",
            )
        }

        Spacer(modifier = Modifier.weight(1f))

        CompactActionButton(
            onClick = onOpenTerminal,
            icon = Icons.Outlined.Computer,
            contentDescription = "Terminal",
            testTag = "chat_terminal_button",
        )
        Spacer(modifier = Modifier.width(dimens.space8))
        CompactActionButton(
            onClick = onNewChat,
            icon = Icons.Default.Add,
            contentDescription = null,
            text = "New",
            testTag = "chat_new_chat_button",
        )
        Spacer(modifier = Modifier.width(dimens.space8))
    }
}
