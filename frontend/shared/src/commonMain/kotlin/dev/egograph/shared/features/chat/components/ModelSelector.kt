package dev.egograph.shared.features.chat.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import dev.egograph.shared.core.domain.model.LLMModel
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens

/**
 * モデル選択コンポーネント
 *
 * ドロップダウンでLLMモデルを選択する。
 *
 * @param models モデル一覧
 * @param selectedModelId 選択中のモデルID
 * @param isLoading 読み込み中フラグ
 * @param error エラーメッセージ
 * @param onModelSelected モデル選択コールバック
 * @param modifier Modifier
 */
@Composable
fun ModelSelector(
    models: List<LLMModel>,
    selectedModelId: String?,
    isLoading: Boolean,
    error: String?,
    onModelSelected: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens
    var expanded by remember { mutableStateOf(false) }

    val selectedModel = models.find { it.id == selectedModelId }

    val displayText =
        when {
            isLoading -> "Loading..."
            error != null -> "Error"
            models.isEmpty() -> "No models"
            selectedModel != null -> selectedModel.name
            else -> "Select Model"
        }

    val isEnabled = !isLoading && error == null && models.isNotEmpty()

    Box(
        modifier =
            modifier
                .testTagResourceId("model_selector"),
    ) {
        Surface(
            color = MaterialTheme.colorScheme.secondaryContainer,
            contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
            shape = MaterialTheme.shapes.small,
            modifier =
                Modifier
                    .testTagResourceId("model_selector_surface")
                    .widthIn(max = dimens.size160)
                    .clickable(enabled = isEnabled) { expanded = !expanded },
        ) {
            Row(
                modifier = Modifier.padding(horizontal = dimens.space10, vertical = dimens.space4),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = displayText,
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier =
                        Modifier
                            .testTagResourceId("model_selector_label"),
                )
                Icon(
                    imageVector = Icons.Filled.ArrowDropDown,
                    contentDescription = null,
                    modifier = Modifier.padding(start = dimens.space4),
                )
            }
        }

        if (isEnabled) {
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
            ) {
                models.forEach { model ->
                    DropdownMenuItem(
                        text = {
                            Column {
                                Text(
                                    text = model.name,
                                    style = MaterialTheme.typography.bodyLarge,
                                )
                                Text(
                                    text = formatCost(model),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        },
                        onClick = {
                            onModelSelected(model.id)
                            expanded = false
                        },
                    )
                }
            }
        }
    }
}

private fun formatCost(model: LLMModel): String {
    if (model.isFree) return "Free"
    val inputCost = model.inputCostPer1m
    val outputCost = model.outputCostPer1m
    return if (inputCost == outputCost) {
        "$${String.format("%.2f", inputCost)}/1M"
    } else {
        "In: $${String.format("%.2f", inputCost)}/1M, Out: $${String.format("%.2f", outputCost)}/1M"
    }
}
