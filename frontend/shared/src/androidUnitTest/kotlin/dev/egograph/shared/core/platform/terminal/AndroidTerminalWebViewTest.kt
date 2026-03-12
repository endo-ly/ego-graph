package dev.egograph.shared.core.platform.terminal

import kotlin.test.Test
import kotlin.test.assertFailsWith

class AndroidTerminalWebViewTest {
    @Test
    fun `createTerminalWebView without Context is unsupported on Android`() {
        assertFailsWith<NotImplementedError> {
            createTerminalWebView()
        }
    }
}
