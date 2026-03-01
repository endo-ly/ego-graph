package dev.egograph.shared.features.chat.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mikepenz.markdown.annotator.annotatorSettings
import com.mikepenz.markdown.compose.LocalMarkdownDimens
import com.mikepenz.markdown.compose.components.markdownComponents
import com.mikepenz.markdown.compose.elements.MarkdownTable
import com.mikepenz.markdown.compose.elements.MarkdownTableBasicText
import com.mikepenz.markdown.compose.elements.highlightedCodeBlock
import com.mikepenz.markdown.compose.elements.highlightedCodeFence
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.m3.markdownColor
import com.mikepenz.markdown.m3.markdownTypography
import com.mikepenz.markdown.model.markdownDimens
import dev.egograph.shared.core.domain.model.MessageRole
import dev.egograph.shared.core.domain.model.ThreadMessage
import dev.egograph.shared.core.ui.common.testTagResourceId
import dev.egograph.shared.core.ui.components.AssistantContentBlock
import dev.egograph.shared.core.ui.components.MermaidDiagram
import dev.egograph.shared.core.ui.components.splitAssistantContent
import dev.egograph.shared.core.ui.theme.EgoGraphThemeTokens
import org.intellij.markdown.ast.ASTNode
import org.intellij.markdown.ast.getTextInNode
import org.intellij.markdown.flavours.gfm.GFMElementTypes.HEADER
import org.intellij.markdown.flavours.gfm.GFMElementTypes.ROW
import org.intellij.markdown.flavours.gfm.GFMTokenTypes.CELL

/**
 * チャットメッセージコンポーネント
 *
 * ユーザーメッセージとアシスタントメッセージを表示する。
 *
 * @param message メッセージ
 * @param modifier Modifier
 * @param isStreaming ストリーミング中フラグ
 * @param activeAssistantTask アクティブなアシスタントタスク
 */
@Composable
fun ChatMessage(
    message: ThreadMessage,
    modifier: Modifier = Modifier,
    isStreaming: Boolean = false,
    activeAssistantTask: String? = null,
) {
    when (message.role) {
        MessageRole.USER -> UserMessage(message, modifier)
        MessageRole.ASSISTANT -> AssistantMessage(message, modifier, isStreaming, activeAssistantTask)
        MessageRole.SYSTEM,
        MessageRole.TOOL,
        -> Unit
    }
}

@Composable
private fun UserMessage(
    message: ThreadMessage,
    modifier: Modifier = Modifier,
) {
    val dimens = EgoGraphThemeTokens.dimens

    Row(
        modifier =
            modifier
                .fillMaxWidth()
                .padding(horizontal = dimens.space16, vertical = dimens.space8),
        horizontalArrangement = Arrangement.End,
    ) {
        Column(
            horizontalAlignment = Alignment.End,
            modifier = Modifier.weight(1f, fill = false),
        ) {
            MessageBubble(isUser = true) {
                Text(
                    text = message.content,
                    modifier = Modifier.padding(dimens.space12),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
        }
    }
}

@Composable
private fun AssistantMessage(
    message: ThreadMessage,
    modifier: Modifier = Modifier,
    isStreaming: Boolean = false,
    activeAssistantTask: String? = null,
) {
    val dimens = EgoGraphThemeTokens.dimens
    val contentBlocks = remember(message.content) { splitAssistantContent(message.content) }
    val textColor = MaterialTheme.colorScheme.onSurfaceVariant
    val assistantBodyStyle =
        MaterialTheme.typography.bodyMedium.copy(
            lineHeight = 28.sp,
        )
    val markdownTextStyles =
        markdownTypography(
            h1 = MaterialTheme.typography.titleLarge,
            h2 = MaterialTheme.typography.titleMedium,
            h3 = MaterialTheme.typography.titleSmall,
            h4 = MaterialTheme.typography.bodyLarge,
            h5 = MaterialTheme.typography.bodyMedium,
            h6 = MaterialTheme.typography.bodyMedium,
            text = assistantBodyStyle,
            paragraph = assistantBodyStyle,
            ordered = assistantBodyStyle,
            bullet = assistantBodyStyle,
            list = assistantBodyStyle,
            table = MaterialTheme.typography.bodySmall.copy(lineHeight = 22.sp),
        )
    val markdownColors = markdownColor(text = textColor)
    val markdownDimens =
        markdownDimens(
            tableCellWidth = 96.dp,
            tableMaxWidth = 360.dp,
            tableCellPadding = 6.dp,
        )
    val markdownRendererComponents =
        remember {
            markdownComponents(
                codeBlock = highlightedCodeBlock,
                codeFence = highlightedCodeFence,
                table = { model ->
                    val columnWeights = remember(model.node, model.content) { calculateTableColumnWeights(model.node, model.content) }
                    MarkdownTable(
                        content = model.content,
                        node = model.node,
                        style = model.typography.table,
                        headerBlock = { content, header, tableWidth, style ->
                            DynamicTableLine(
                                content = content,
                                row = header,
                                tableWidth = tableWidth,
                                style = style.copy(fontWeight = FontWeight.Bold),
                                columnWeights = columnWeights,
                            )
                        },
                        rowBlock = { content, row, tableWidth, style ->
                            DynamicTableLine(
                                content = content,
                                row = row,
                                tableWidth = tableWidth,
                                style = style,
                                columnWeights = columnWeights,
                            )
                        },
                    )
                },
            )
        }

    Row(
        modifier =
            modifier
                .fillMaxWidth()
                .padding(horizontal = dimens.space16, vertical = dimens.space8),
        horizontalArrangement = Arrangement.Start,
    ) {
        Column(
            horizontalAlignment = Alignment.Start,
            modifier = Modifier.weight(1f),
        ) {
            if (!isStreaming) {
                contentBlocks.forEach { block ->
                    when (block) {
                        is AssistantContentBlock.Markdown -> {
                            Markdown(
                                content = block.content,
                                modifier = Modifier.padding(horizontal = dimens.space6, vertical = dimens.space4),
                                colors = markdownColors,
                                typography = markdownTextStyles,
                                components = markdownRendererComponents,
                                dimens = markdownDimens,
                            )
                        }

                        is AssistantContentBlock.Mermaid -> {
                            MermaidDiagram(
                                mermaidCode = block.code,
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                }
            } else {
                if (message.content.isBlank()) {
                    val statusText = activeAssistantTask?.let { "Running $it..." } ?: "Thinking..."
                    Row(
                        modifier = Modifier.padding(horizontal = dimens.space6, vertical = dimens.space4),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(dimens.iconSizeSmall),
                            strokeWidth = dimens.space2,
                            color = MaterialTheme.colorScheme.secondary,
                        )
                        Spacer(modifier = Modifier.width(dimens.space8))
                        Text(
                            text = statusText,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    Markdown(
                        content = message.content,
                        modifier = Modifier.padding(horizontal = dimens.space6, vertical = dimens.space4),
                        colors = markdownColors,
                        typography = markdownTextStyles,
                        components = markdownRendererComponents,
                        dimens = markdownDimens,
                    )
                }
            }

            if (message.modelName != null) {
                Text(
                    text = message.modelName,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
                    modifier = Modifier.padding(top = dimens.space4, start = dimens.space4),
                )
            }
        }
    }
}

private fun calculateTableColumnWeights(
    tableNode: ASTNode,
    content: String,
): List<Float> {
    val rows = tableNode.children.filter { it.type == HEADER || it.type == ROW }
    val columnCount = rows.maxOfOrNull { row -> row.children.count { it.type == CELL } } ?: return emptyList()
    val maxLengths = MutableList(columnCount) { 1 }

    rows.forEach { row ->
        row.children.filter { it.type == CELL }.forEachIndexed { index, cell ->
            val normalizedLength =
                cell
                    .getTextInNode(content)
                    .toString()
                    .trim()
                    .replace('\n', ' ')
                    .length
                    .coerceAtLeast(1)
            if (normalizedLength > maxLengths[index]) {
                maxLengths[index] = normalizedLength
            }
        }
    }

    return maxLengths.map { length ->
        val boundedLength = length.coerceIn(6, 36)
        boundedLength.toFloat()
    }
}

@Composable
private fun DynamicTableLine(
    content: String,
    row: ASTNode,
    tableWidth: androidx.compose.ui.unit.Dp,
    style: androidx.compose.ui.text.TextStyle,
    columnWeights: List<Float>,
) {
    val tableCellPadding = LocalMarkdownDimens.current.tableCellPadding
    val cells = row.children.filter { it.type == CELL }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.widthIn(max = tableWidth).height(IntrinsicSize.Max),
    ) {
        cells.forEachIndexed { index, cell ->
            val columnWeight = columnWeights.getOrNull(index) ?: 1f
            Column(
                modifier =
                    Modifier
                        .padding(tableCellPadding)
                        .weight(columnWeight.coerceAtLeast(1f)),
            ) {
                MarkdownTableBasicText(
                    content = content,
                    cell = cell,
                    style = style,
                    maxLines = Int.MAX_VALUE,
                    overflow = TextOverflow.Clip,
                    annotatorSettings = annotatorSettings(),
                )
            }
        }
    }
}

@Composable
private fun MessageBubble(
    isUser: Boolean,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val shapes = EgoGraphThemeTokens.shapes

    Surface(
        shape = shapes.radiusMd,
        color =
            if (isUser) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            },
        modifier =
            modifier
                .testTagResourceId(if (isUser) "user_message_bubble" else "assistant_message_bubble"),
    ) {
        content()
    }
}
