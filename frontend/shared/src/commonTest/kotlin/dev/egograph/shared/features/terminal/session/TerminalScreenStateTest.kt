package dev.egograph.shared.features.terminal.session

import dev.egograph.shared.core.platform.terminal.CopyResult
import kotlin.test.Test
import kotlin.test.assertEquals

class TerminalScreenStateTest {
    @Test
    fun `copyFeedbackMessage returns success copy text`() {
        assertEquals(
            "Copied terminal text",
            copyFeedbackMessage(CopyResult.Success("prompt output")),
        )
    }

    @Test
    fun `copyFeedbackMessage returns failure copy text`() {
        assertEquals(
            "Copy failed",
            copyFeedbackMessage(CopyResult.Error("Clipboard unavailable")),
        )
    }
}
