package dev.egograph.shared.core.platform.terminal

import kotlinx.coroutines.flow.Flow

/**
 * Terminal WebView interface for platform-specific implementations
 *
 * Provides WebView functionality for rendering xterm.js terminal
 * and handling JavaScript bridge communication.
 */
interface TerminalWebView {
    /**
     * Load the terminal.html file from assets
     */
    fun loadTerminal()

    /**
     * Connect to WebSocket endpoint
     *
     * @param wsUrl WebSocket URL to connect to
     * @param wsToken WebSocket authentication token for post-connect authentication
     */
    fun connect(
        wsUrl: String,
        wsToken: String,
    )

    /**
     * Disconnect from WebSocket
     */
    fun disconnect()

    /**
     * Send a special key sequence to the terminal
     *
     * @param key Key sequence to send (e.g., "\u0001" for Ctrl+A)
     */
    fun sendKey(key: String)

    /**
     * Copy the current terminal selection to the system clipboard.
     */
    fun copySelectionToClipboard()

    /**
     * Paste the current system clipboard text into the terminal.
     */
    fun pasteFromClipboard()

    /**
     * Enable or disable text selection mode.
     */
    fun setSelectionMode(enabled: Boolean)

    /**
     * Clear any active text selection in the terminal.
     */
    fun clearSelection()

    /**
     * Focus terminal input and move viewport to the latest line.
     *
     * Used when software keyboard becomes visible so input always targets
     * the current prompt at the bottom.
     */
    fun focusInputAtBottom()

    /**
     * Apply terminal color theme.
     *
     * @param darkMode true for dark theme, false for light theme
     */
    fun setTheme(darkMode: Boolean)

    /**
     * Flow of connection state changes
     * Emits true when connected, false when disconnected
     */
    val connectionState: Flow<Boolean>

    /**
     * Flow of errors
     * Emits error messages
     */
    val errors: Flow<String>

    /**
     * Flow of user-visible terminal messages such as clipboard actions.
     */
    val messages: Flow<String>

    /**
     * Emits whether text selection mode is active.
     */
    val selectionMode: Flow<Boolean>
}

/**
 * Factory for creating TerminalWebView instances
 */
expect fun createTerminalWebView(): TerminalWebView
