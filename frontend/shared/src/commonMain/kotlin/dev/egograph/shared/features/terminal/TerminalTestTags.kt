package dev.egograph.shared.features.terminal

/**
 * Terminal機能用のテストタグ定数
 *
 * Maestro E2EテストおよびCompose UIテストで使用する安定したタグ名を定義します。
 * これらのタグは `testTagsAsResourceId = true` と共に使用され、
 * リソースIDとしてAndroid UI Automationからアクセス可能です。
 */
object TerminalTestTags {
    /** セッションリストアイテムのルートタグ */
    const val SESSION_ITEM = "session_item"

    /** セッションプレビュー（ターミナルスナップショット表示）のタグ */
    const val SESSION_PREVIEW = "session_preview"

    /** ターミナル接続状態を示すステータスピルのタグ */
    const val TERMINAL_STATUS_PILL = "terminal_status_pill"

    /** ターミナル画面の戻るボタンのタグ */
    const val TERMINAL_BACK_BUTTON = "terminal_back_button"

    /** ターミナル内容をコピーするボタンのタグ */
    const val TERMINAL_COPY_BUTTON = "terminal_copy_button"

    /** クリップボード内容を貼り付けるボタンのタグ */
    const val TERMINAL_PASTE_BUTTON = "terminal_paste_button"
}
