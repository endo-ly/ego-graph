package dev.egograph.shared.features.sidebar

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.Text
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.koin.koinScreenModel
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import dev.egograph.shared.features.chat.ChatScreen
import dev.egograph.shared.features.chat.ChatScreenModel
import dev.egograph.shared.features.chat.ChatState
import dev.egograph.shared.features.chat.threads.ThreadList
import dev.egograph.shared.features.navigation.MainNavigationHost
import dev.egograph.shared.features.navigation.MainView
import dev.egograph.shared.features.settings.SettingsScreen
import dev.egograph.shared.features.systemprompt.SystemPromptEditorScreen
import kotlinx.coroutines.launch

/**
 * サイドバー画面
 *
 * ナビゲーションコントローラーと画面コンテンツを管理するメイン画面。
 */
class SidebarScreen : Screen {
    @Composable
    override fun Content() {
        val dimens = EgoGraphThemeTokens.dimens
        val screenModel = koinScreenModel<ChatScreenModel>()
        val state: ChatState by screenModel.state.collectAsState()
        val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
        val scope = rememberCoroutineScope()
        var activeView by rememberSaveable { mutableStateOf(MainView.Chat) }
        val keyboardController = LocalSoftwareKeyboardController.current
        val focusManager = LocalFocusManager.current

        val dismissKeyboard = {
            keyboardController?.hide()
            focusManager.clearFocus(force = true)
        }

        val chatScreen =
            remember(drawerState, scope, screenModel) {
                ChatScreen(
                    onOpenSidebar = {
                        dismissKeyboard()
                        scope.launch { drawerState.open() }
                    },
                    onNewChat = {
                        activeView = MainView.Chat
                        screenModel.clearThreadSelection()
                    },
                )
            }

        LaunchedEffect(drawerState) {
            snapshotFlow { drawerState.targetValue }
                .collect { targetValue ->
                    if (targetValue == DrawerValue.Open) {
                        dismissKeyboard()
                    }
                }
        }

        ModalNavigationDrawer(
            drawerState = drawerState,
            drawerContent = {
                ModalDrawerSheet {
                    Column(
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .padding(horizontal = dimens.space16, vertical = dimens.space12),
                    ) {
                        Text(
                            text = "History",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    HorizontalDivider()

                    ThreadList(
                        threads = state.threadList.threads,
                        selectedThreadId = state.threadList.selectedThread?.threadId,
                        isLoading = state.threadList.isLoading,
                        isLoadingMore = state.threadList.isLoadingMore,
                        hasMore = state.threadList.hasMore,
                        error = state.threadList.error,
                        onThreadClick = { threadId ->
                            activeView = MainView.Chat
                            screenModel.selectThread(threadId)
                            scope.launch { drawerState.close() }
                        },
                        onRefresh = {
                            screenModel.loadThreads()
                        },
                        onLoadMore = {
                            screenModel.loadMoreThreads()
                        },
                        modifier = Modifier.weight(1f),
                    )

                    HorizontalDivider()

                    Spacer(modifier = Modifier.height(dimens.space8))

                    SidebarFooter(
                        onNewChatClick = {
                            activeView = MainView.Chat
                            screenModel.clearThreadSelection()
                            scope.launch { drawerState.close() }
                        },
                        onSettingsClick = {
                            activeView = MainView.Settings
                            scope.launch { drawerState.close() }
                        },
                        onSystemPromptClick = {
                            activeView = MainView.SystemPrompt
                            scope.launch { drawerState.close() }
                        },
                    )

                    Spacer(modifier = Modifier.height(dimens.space12))
                }
            },
            gesturesEnabled = activeView == MainView.Chat,
        ) {
            MainNavigationHost(
                activeView = activeView,
                onSwipeToSidebar = {
                    dismissKeyboard()
                    scope.launch { drawerState.open() }
                },
                onSwipeToOther = {
                    // スワイプ機構は維持。将来のView追加時に使用可能
                },
            ) { targetView ->
                when (targetView) {
                    MainView.Chat -> chatScreen.Content()
                    MainView.SystemPrompt -> {
                        val promptScreen =
                            remember {
                                SystemPromptEditorScreen(
                                    onBack = { activeView = MainView.Chat },
                                )
                            }
                        promptScreen.Content()
                    }

                    MainView.Settings -> {
                        val settingsScreen =
                            remember {
                                SettingsScreen(
                                    onBack = { activeView = MainView.Chat },
                                )
                            }
                        settingsScreen.Content()
                    }
                }
            }
        }
    }
}
