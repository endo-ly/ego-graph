package dev.egograph.shared.features.systemprompt

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import cafe.adriel.voyager.core.screen.Screen
import cafe.adriel.voyager.koin.koinScreenModel
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * システムプロンプトエディタ画面
 *
 * ユーザー定義のシステムプロンプトを編集する画面。
 *
 * @param onBack 戻るボタンコールバック
 */
class SystemPromptEditorScreen(
    private val onBack: () -> Unit = {},
) : Screen {
    @Composable
    override fun Content() {
        val dimens = EgoGraphThemeTokens.dimens
        val screenModel = koinScreenModel<SystemPromptEditorScreenModel>()
        val state by screenModel.state.collectAsState()
        val snackbarHostState = remember { SnackbarHostState() }

        LaunchedEffect(Unit) {
            screenModel.effect.collect { effect ->
                when (effect) {
                    is SystemPromptEditorEffect.ShowMessage -> snackbarHostState.showSnackbar(effect.message)
                }
            }
        }

        Scaffold(
            snackbarHost = { SnackbarHost(snackbarHostState) },
            bottomBar = {
                Column {
                    SystemPromptTabs(
                        selectedTab = state.selectedTab,
                        onTabSelected = screenModel::onTabSelected,
                    )
                    Row(
                        modifier = Modifier.padding(dimens.space16),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Spacer(Modifier.weight(1f))
                        TextButton(
                            onClick = onBack,
                            enabled = !state.isLoading,
                            modifier =
                                Modifier
                                    .testTagResourceId("back_button"),
                        ) {
                            Text("Cancel")
                        }
                        Spacer(Modifier.width(dimens.space8))
                        Button(
                            onClick = screenModel::saveSelectedPrompt,
                            enabled = state.canSave,
                            modifier =
                                Modifier
                                    .testTagResourceId("save_prompt_button"),
                        ) {
                            Text("Save")
                        }
                    }
                }
            },
        ) { paddingValues ->
            Column(modifier = Modifier.padding(paddingValues).fillMaxSize()) {
                if (state.isLoading) {
                    CircularProgressIndicator(
                        modifier =
                            Modifier
                                .align(Alignment.CenterHorizontally)
                                .padding(dimens.space16),
                    )
                }

                SystemPromptEditor(
                    content = state.draftContent,
                    onContentChange = screenModel::onDraftChanged,
                    enabled = !state.isLoading,
                    modifier =
                        Modifier
                            .weight(1f)
                            .padding(dimens.space16),
                )
            }
        }
    }
}
