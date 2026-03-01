package dev.egograph.shared.features.chat.components

import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Mic
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
import androidx.compose.ui.unit.dp
import dev.egograph.shared.core.domain.model.LLMModel
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

internal object ChatComposerMetrics {
    val outerHorizontalPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space20

    val outerVerticalPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space12

    val actionButtonsSpacing
        @Composable get() = EgoGraphThemeTokens.dimens.space8

    val containerMinHeight
        @Composable get() = EgoGraphThemeTokens.dimens.chatComposerMinHeight

    const val INPUT_MIN_LINES = 2
    const val INPUT_MAX_LINES = 5

    val contentHorizontalPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space16

    val contentTopPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space12

    val contentBottomPadding
        @Composable get() = EgoGraphThemeTokens.dimens.space8

    val textLaneMinHeight = 50.dp

    val modelSelectorSpacing
        @Composable get() = EgoGraphThemeTokens.dimens.space8
}

@OptIn(ExperimentalMaterial3Api::class)
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
    modifier: Modifier = Modifier,
) {
    val interactionSource = remember { MutableInteractionSource() }
    val isFocused = interactionSource.collectIsFocusedAsState().value
    val dimens = EgoGraphThemeTokens.dimens
    val shapes = EgoGraphThemeTokens.shapes

    val colors = OutlinedTextFieldDefaults.colors()
    val shape: Shape = shapes.radiusXl

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
        decorationBox = { innerTextField ->
            Surface(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .clip(shape)
                        .border(
                            width = dimens.borderWidthThin,
                            color = MaterialTheme.colorScheme.outline,
                            shape = shape,
                        ),
                shape = shape,
                color = colors.unfocusedContainerColor,
                contentColor = colors.unfocusedTextColor,
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
                    ChatModelSelector(
                        models = models,
                        selectedModelId = selectedModelId,
                        isLoading = isLoadingModels,
                        error = modelsError,
                        onModelSelected = onModelSelected,
                        modifier = Modifier.align(Alignment.Start),
                    )
                }
            }
        },
    )
}

@Composable
internal fun MicButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    IconButton(
        onClick = onClick,
        modifier = modifier.testTagResourceId("mic_button"),
    ) {
        Icon(
            imageVector = Icons.Filled.Mic,
            contentDescription = "Voice input",
        )
    }
}

@Composable
internal fun SendButton(
    enabled: Boolean,
    onClick: () -> Unit,
) {
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.testTagResourceId("send_button"),
    ) {
        Icon(
            imageVector = Icons.AutoMirrored.Filled.Send,
            contentDescription = "Send",
        )
    }
}
