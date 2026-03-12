package dev.egograph.shared.features.terminal.agentlist.components

import dev.egograph.shared.core.domain.model.terminal.Session
import dev.egograph.shared.core.domain.model.terminal.SessionStatus
import kotlin.test.Test
import kotlin.test.assertEquals

class SessionListItemStateTest {
    private fun session(
        previewAvailable: Boolean,
        previewLines: List<String>,
    ) = Session(
        sessionId = "agent-0001",
        name = "agent-api-server",
        status = SessionStatus.CONNECTED,
        lastActivity = "2026-03-11T16:00:00Z",
        createdAt = "2026-03-11T15:00:00Z",
        previewAvailable = previewAvailable,
        previewLines = previewLines,
    )

    @Test
    fun `previewDisplayLines keeps all preview rows`() {
        val lines = previewDisplayLines(session(true, listOf("1", "2", "3", "4", "5")))

        assertEquals(listOf("1", "2", "3", "4", "5"), lines)
    }

    @Test
    fun `previewDisplayLines returns deterministic fallback when preview unavailable`() {
        val lines = previewDisplayLines(session(false, emptyList()))

        assertEquals(listOf("Preview unavailable"), lines)
    }

    @Test
    fun `previewDisplayLines prefers preview lines even when availability flag is false`() {
        val lines = previewDisplayLines(session(false, listOf("cached preview")))

        assertEquals(listOf("cached preview"), lines)
    }

    @Test
    fun `sessionSubtitle hides duplicate session name`() {
        assertEquals(
            null,
            sessionSubtitle(
                session(true, listOf("preview")).copy(name = "agent-0001"),
            ),
        )
    }
}
