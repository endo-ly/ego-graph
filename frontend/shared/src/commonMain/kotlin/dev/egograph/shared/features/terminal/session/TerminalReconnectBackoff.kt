package dev.egograph.shared.features.terminal.session

import kotlin.random.Random

/**
 * Terminal Reconnect Backoff Calculator
 *
 * Exponential backoff with jitter for WebSocket reconnection attempts.
 *
 * @property baseDelayMs Base delay in milliseconds (default: 1000ms)
 * @property maxDelayMs Maximum delay in milliseconds (default: 30000ms)
 * @property multiplier Multiplier for exponential backoff (default: 2.0)
 * @property jitterPercentage Percentage for jitter calculation +/- 20% (default: 0.2)
 * @property random Random instance for jitter calculation (injectable for testing)
 */
data class TerminalReconnectBackoff(
    private val baseDelayMs: Long = 1000L,
    private val maxDelayMs: Long = 30000L,
    private val multiplier: Double = 2.0,
    private val jitterPercentage: Double = 0.2,
    private val random: Random = Random.Default,
) {
    init {
        require(baseDelayMs > 0) { "baseDelayMs must be positive" }
        require(maxDelayMs >= baseDelayMs) { "maxDelayMs must be >= baseDelayMs" }
        require(multiplier > 1.0) { "multiplier must be > 1.0" }
        require(jitterPercentage >= 0.0 && jitterPercentage <= 1.0) {
            "jitterPercentage must be between 0.0 and 1.0"
        }
    }

    /**
     * Calculate delay for the given attempt number
     *
     * @param attempt Attempt number (0-based)
     * @return Delay in milliseconds
     */
    fun calculateDelay(attempt: Int): Long {
        require(attempt >= 0) { "attempt must be >= 0, was $attempt" }
        val exponentialDelay = (baseDelayMs * multiplier.pow(attempt)).toLong()
        val cappedDelay = minOf(exponentialDelay, maxDelayMs)

        return if (jitterPercentage > 0.0) {
            val jitterRange = (cappedDelay * jitterPercentage).toLong()
            val minDelay = maxOf(cappedDelay - jitterRange, baseDelayMs)
            val maxDelay = minOf(cappedDelay + jitterRange, maxDelayMs)
            if (maxDelay <= minDelay) {
                minDelay
            } else {
                random.nextLong(minDelay, maxDelay + 1)
            }
        } else {
            cappedDelay
        }
    }

    /**
     * Reset state for a new connection cycle
     *
     * This is a no-op in this pure functional implementation,
     * but provided for API compatibility with stateful implementations.
     */
    fun reset() {
        // No-op in pure functional implementation
    }

    private fun Double.pow(exponent: Int): Double {
        require(exponent >= 0) { "attempt must be >= 0, was $exponent" }
        var result = 1.0
        repeat(exponent) {
            result *= this
        }
        return result
    }
}

/**
 * Create a default TerminalReconnectBackoff instance
 */
fun createTerminalReconnectBackoff(): TerminalReconnectBackoff = TerminalReconnectBackoff()

/**
 * Create a TerminalReconnectBackoff instance with deterministic Random for testing
 *
 * @param seed Seed for Random instance
 */
fun createTerminalReconnectBackoffForTesting(seed: Int = 0): TerminalReconnectBackoff =
    TerminalReconnectBackoff(
        jitterPercentage = 0.0,
        random = Random(seed),
    )
