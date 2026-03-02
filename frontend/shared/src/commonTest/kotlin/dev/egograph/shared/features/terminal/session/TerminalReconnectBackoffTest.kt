package dev.egograph.shared.features.terminal.session

import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class TerminalReconnectBackoffTest {
    @Test
    fun `calculateDelay returns base delay for attempt 0`() {
        val backoff = createTerminalReconnectBackoffForTesting(seed = 0)
        val delay = backoff.calculateDelay(0)
        assertEquals(1000L, delay)
    }

    @Test
    fun `calculateDelay applies exponential backoff`() {
        val backoff =
            TerminalReconnectBackoff(
                baseDelayMs = 1000L,
                maxDelayMs = 30000L,
                multiplier = 2.0,
                jitterPercentage = 0.0,
                random = Random(0),
            )

        // Without jitter, delays should be deterministic
        assertEquals(1000L, backoff.calculateDelay(0))
        assertEquals(2000L, backoff.calculateDelay(1))
        assertEquals(4000L, backoff.calculateDelay(2))
        assertEquals(8000L, backoff.calculateDelay(3))
        assertEquals(16000L, backoff.calculateDelay(4))
        assertEquals(30000L, backoff.calculateDelay(5)) // Capped at max
        assertEquals(30000L, backoff.calculateDelay(10)) // Still capped
    }

    @Test
    fun `calculateDelay respects max delay`() {
        val backoff =
            TerminalReconnectBackoff(
                baseDelayMs = 1000L,
                maxDelayMs = 5000L,
                multiplier = 3.0,
                jitterPercentage = 0.0,
                random = Random(0),
            )

        assertEquals(1000L, backoff.calculateDelay(0))
        assertEquals(3000L, backoff.calculateDelay(1))
        assertEquals(5000L, backoff.calculateDelay(2)) // Capped
        assertEquals(5000L, backoff.calculateDelay(3)) // Capped
        assertEquals(5000L, backoff.calculateDelay(10)) // Capped
    }

    @Test
    fun `calculateDelay applies jitter with Random(0)`() {
        val backoff =
            TerminalReconnectBackoff(
                baseDelayMs = 1000L,
                maxDelayMs = 30000L,
                multiplier = 2.0,
                jitterPercentage = 0.2,
                random = Random(0),
            )

        // With Random(0), the jitter values should be deterministic
        val delay0 = backoff.calculateDelay(0)
        val delay1 = backoff.calculateDelay(1)
        val delay2 = backoff.calculateDelay(2)

        // Verify jitter is within expected range (+/- 20%)
        // For base delay 1000ms, jitter range is 200ms, constrained by baseDelay: [1000, 1200]
        assertTrue(delay0 >= 1000L && delay0 <= 1200L, "delay0=$delay0 should be in [1000, 1200]")

        // For attempt 1, exponential delay is 2000ms, jitter range is 400ms: [1600, 2400]
        assertTrue(delay1 >= 1600L && delay1 <= 2400L, "delay1=$delay1 should be in [1600, 2400]")

        // For attempt 2, exponential delay is 4000ms, jitter range is 800ms: [3200, 4800]
        assertTrue(delay2 >= 3200L && delay2 <= 4800L, "delay2=$delay2 should be in [3200, 4800]")
    }

    @Test
    fun `calculateDelay with zero jitter returns deterministic values`() {
        val backoff =
            TerminalReconnectBackoff(
                baseDelayMs = 1000L,
                maxDelayMs = 30000L,
                multiplier = 2.0,
                jitterPercentage = 0.0,
                random = Random(0),
            )

        // Multiple calls should return the same value
        assertEquals(1000L, backoff.calculateDelay(0))
        assertEquals(1000L, backoff.calculateDelay(0))
        assertEquals(2000L, backoff.calculateDelay(1))
        assertEquals(2000L, backoff.calculateDelay(1))
    }

    @Test
    fun `calculateDelay never goes below base delay even with jitter`() {
        val backoff =
            TerminalReconnectBackoff(
                baseDelayMs = 1000L,
                maxDelayMs = 30000L,
                multiplier = 1.5,
                jitterPercentage = 0.5, // High jitter
                random = Random(0),
            )

        repeat(100) { attempt ->
            val delay = backoff.calculateDelay(attempt)
            assertTrue(
                delay >= 1000L,
                "Delay $delay for attempt $attempt should be >= base delay (1000ms)",
            )
        }
    }

    @Test
    fun `calculateDelay rejects negative attempt`() {
        val backoff = createTerminalReconnectBackoffForTesting(seed = 0)

        val exception =
            assertThrows<IllegalArgumentException> {
                backoff.calculateDelay(-1)
            }

        assertTrue(exception.message!!.contains("attempt must be >= 0"))
    }

    @Test
    fun `createTerminalReconnectBackoffForTesting creates deterministic instance`() {
        val backoff1 = createTerminalReconnectBackoffForTesting(seed = 42)
        val backoff2 = createTerminalReconnectBackoffForTesting(seed = 42)

        // Same seed should produce same values
        repeat(10) { attempt ->
            assertEquals(backoff1.calculateDelay(attempt), backoff2.calculateDelay(attempt))
        }
    }

    @Test
    fun `reset is no-op for pure functional implementation`() {
        val backoff = createTerminalReconnectBackoffForTesting(seed = 0)

        // Get some delays
        val delay1 = backoff.calculateDelay(1)
        val delay2 = backoff.calculateDelay(2)

        // Reset
        backoff.reset()

        // Pure functional implementation should return same values after reset
        assertEquals(delay1, backoff.calculateDelay(1))
        assertEquals(delay2, backoff.calculateDelay(2))
    }

    @Test
    fun `constructor validates baseDelayMs is positive`() {
        val exception =
            assertThrows<IllegalArgumentException> {
                TerminalReconnectBackoff(
                    baseDelayMs = 0,
                    maxDelayMs = 30000L,
                    multiplier = 2.0,
                    jitterPercentage = 0.2,
                    random = Random(0),
                )
            }
        assertTrue(exception.message!!.contains("baseDelayMs must be positive"))
    }

    @Test
    fun `constructor validates maxDelayMs is greater than or equal to baseDelayMs`() {
        val exception =
            assertThrows<IllegalArgumentException> {
                TerminalReconnectBackoff(
                    baseDelayMs = 1000L,
                    maxDelayMs = 500L,
                    multiplier = 2.0,
                    jitterPercentage = 0.2,
                    random = Random(0),
                )
            }
        assertTrue(exception.message!!.contains("maxDelayMs must be >= baseDelayMs"))
    }

    @Test
    fun `constructor validates multiplier is greater than 1`() {
        val exception =
            assertThrows<IllegalArgumentException> {
                TerminalReconnectBackoff(
                    baseDelayMs = 1000L,
                    maxDelayMs = 30000L,
                    multiplier = 1.0,
                    jitterPercentage = 0.2,
                    random = Random(0),
                )
            }
        assertTrue(exception.message!!.contains("multiplier must be > 1.0"))
    }

    @Test
    fun `constructor validates jitterPercentage is between 0 and 1`() {
        val exception1 =
            assertThrows<IllegalArgumentException> {
                TerminalReconnectBackoff(
                    baseDelayMs = 1000L,
                    maxDelayMs = 30000L,
                    multiplier = 2.0,
                    jitterPercentage = -0.1,
                    random = Random(0),
                )
            }
        assertTrue(exception1.message!!.contains("jitterPercentage must be between 0.0 and 1.0"))

        val exception2 =
            assertThrows<IllegalArgumentException> {
                TerminalReconnectBackoff(
                    baseDelayMs = 1000L,
                    maxDelayMs = 30000L,
                    multiplier = 2.0,
                    jitterPercentage = 1.1,
                    random = Random(0),
                )
            }
        assertTrue(exception2.message!!.contains("jitterPercentage must be between 0.0 and 1.0"))
    }
}

/**
 * Helper function to assert that a block throws an exception of the expected type
 */
private inline fun <reified T : Throwable> assertThrows(block: () -> Unit): T {
    var exception: Throwable? = null
    try {
        block()
    } catch (e: Throwable) {
        exception = e
    }

    @Suppress("UNCHECKED_CAST")
    return exception as? T
        ?: throw AssertionError(
            "Expected ${T::class.simpleName} to be thrown, but got ${exception?.let { it::class.simpleName } ?: "no exception"}",
        )
}
