package dev.egograph.shared.features.chat.components

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import dev.egograph.shared.core.domain.model.LLMModel
import dev.egograph.shared.core.ui.components.rememberVoiceInputCoordinator

/**
 * チャット入力欄と送信/音声入力操作をまとめたコンポーザー。
 *
 * @param models モデル選択に表示する候補一覧
 * @param selectedModelId 現在選択中のモデルID
 * @param isLoadingModels モデル一覧の読み込み状態
 * @param modelsError モデル一覧取得エラー
 * @param onModelSelected モデル選択時のコールバック
 * @param onSendMessage 送信時のコールバック
 * @param isLoading メッセージ送信中かどうか
 * @param modifier 追加のModifier
 */
@Composable
fun ChatComposer(
    models: List<LLMModel>,
    selectedModelId: String?,
    isLoadingModels: Boolean,
    modelsError: String?,
    onModelSelected: (String) -> Unit,
    onSendMessage: (String) -> Unit,
    isLoading: Boolean = false,
    modifier: Modifier = Modifier,
) {
    var text by remember { mutableStateOf("") }
    val voiceInputCoordinator =
        rememberVoiceInputCoordinator(
            onRecognizedText = { recognizedText ->
                val current = text.trim()
                val recognized = recognizedText.trim()
                if (recognized.isNotEmpty()) {
                    text =
                        if (current.isEmpty()) {
                            recognized
                        } else {
                            "$current $recognized"
                        }
                }
            },
            onError = { _ -> },
        )

    ChatComposerField(
        text = text,
        onTextChange = { text = it },
        isLoading = isLoading,
        models = models,
        selectedModelId = selectedModelId,
        isLoadingModels = isLoadingModels,
        modelsError = modelsError,
        onModelSelected = onModelSelected,
        onSendMessage = {
            onSendMessage(text)
            text = ""
        },
        onVoiceInputClick = voiceInputCoordinator.onToggle,
        isVoiceInputActive = voiceInputCoordinator.isActive,
        modifier =
            modifier
                .fillMaxWidth()
                .padding(
                    horizontal = ChatComposerMetrics.outerHorizontalPadding,
                    vertical = ChatComposerMetrics.outerVerticalPadding,
                ),
    )
}
