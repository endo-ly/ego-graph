package dev.egograph.shared.features.chat.components

import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.unit.dp
import dev.egograph.shared.core.domain.model.LLMModel
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.components.VoiceInputToggleButton
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

internal object ChatComposerMetrics {
    val outerHorizontalPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space12

    val outerVerticalPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space12

    val actionButtonsSpacing
        @Composable get() = EgoGraphThemeTokens.dimens.space8

    val containerMinHeight
        @Composable get() = EgoGraphThemeTokens.dimens.chatComposerMinHeight

    const val INPUT_MIN_LINES = 1
    const val INPUT_MAX_LINES = 3

    val contentHorizontalPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space16

    val contentTopPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space12

    val contentBottomPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space8

    val textLaneMinHeight = 30.dp

    val modelSelectorSpacing
        @Composable get() = EgoGraphThemeTokens.dimens.space8
}

@OptIn(ExperimentalMaterial3Api::class)
/**
 * チャット入力本体のUI。
 *
 * モデル選択、送信、音声入力ボタンを同一コンテナで扱う。
 */
@Composable
internal fun ChatComposerField(
    text: String,
    onTextChange: (String) -> Unit,
    isLoading: Boolean,
    models: List<LLMModel>,
    selectedModelId: String?,
    isLoadingModels: Boolean,
    modelsError: String?,
    onModelSelected: (String) -> Unit,
    onSendMessage: () -> Unit,
    onVoiceInputClick: (() -> Unit)? = null,
    isVoiceInputActive: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val interactionSource = remember { MutableInteractionSource() }
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes

    val colors = OutlinedTextFieldDefaults.colors()
    val shape: Shape = shapes.radiusXl
    val accentBlue = EgoGraphThemeTokens.accentBlue
    val inputContainerColor = MaterialTheme.colorScheme.surfaceVariant
    val inputBorderColor = MaterialTheme.colorScheme.outline

    BasicTextField(
        value = text,
        onValueChange = onTextChange,
        modifier =
            modifier
                .testTagResourceId("chat_input_field")
                .fillMaxWidth()
                .heightIn(min = ChatComposerMetrics.containerMinHeight),
        textStyle =
            LocalTextStyle.current.copy(color = colors.unfocusedTextColor),
        enabled = !isLoading,
        minLines = ChatComposerMetrics.INPUT_MIN_LINES,
        maxLines = ChatComposerMetrics.INPUT_MAX_LINES,
        interactionSource = interactionSource,
        cursorBrush = SolidColor(accentBlue),
        decorationBox = { innerTextField ->
            Surface(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .clip(shape)
                        .border(
                            width = dimens.borderWidthThin,
                            color = inputBorderColor,
                            shape = shape,
                        ),
                shape = shape,
                color = inputContainerColor,
                contentColor = MaterialTheme.colorScheme.onSurface,
            ) {
                Column(
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .padding(
                                start = ChatComposerMetrics.contentHorizontalPadding,
                                top = ChatComposerMetrics.contentTopPadding,
                                end = ChatComposerMetrics.contentHorizontalPadding,
                                bottom = ChatComposerMetrics.contentBottomPadding,
                            ),
                ) {
                    Box(
                        modifier = Modifier.fillMaxWidth().heightIn(min = ChatComposerMetrics.textLaneMinHeight),
                    ) {
                        if (text.isEmpty()) {
                            Text(
                                text = "Type a message...",
                                color = colors.unfocusedPlaceholderColor,
                            )
                        }
                        innerTextField()
                    }
                    Spacer(modifier = Modifier.height(ChatComposerMetrics.modelSelectorSpacing))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        ChatModelSelector(
                            models = models,
                            selectedModelId = selectedModelId,
                            isLoading = isLoadingModels,
                            error = modelsError,
                            onModelSelected = onModelSelected,
                            modifier = Modifier.weight(1f),
                        )

                        onVoiceInputClick?.let { voiceInputClick ->
                            Spacer(modifier = Modifier.width(ChatComposerMetrics.actionButtonsSpacing))
                            VoiceInputToggleButton(
                                isActive = isVoiceInputActive,
                                onClick = voiceInputClick,
                                testTag = "mic_button",
                            )
                        }

                        Spacer(modifier = Modifier.width(ChatComposerMetrics.actionButtonsSpacing))
                        SendButton(
                            enabled = text.isNotBlank() && !isLoading,
                            onClick = onSendMessage,
                        )
                    }
                }
            }
        },
    )
}

/**
 * 送信アイコンボタン。
 *
 * @param enabled 押下可能かどうか
 * @param onClick 押下時の処理
 */
@Composable
internal fun SendButton(
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val accentBlue = EgoGraphThemeTokens.accentBlue

    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.testTagResourceId("send_button"),
    ) {
        Icon(
            imageVector = Icons.AutoMirrored.Filled.Send,
            contentDescription = "Send",
            tint = if (enabled) accentBlue else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
