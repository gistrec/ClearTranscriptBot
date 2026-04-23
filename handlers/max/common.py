"""Shared keyboard builders for Max messenger handlers."""
from aiomax.buttons import CallbackButton, KeyboardBuilder


def make_confirm_keyboard(task_id: int) -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(
            CallbackButton("Распознать", f"create_task:{task_id}"),
            CallbackButton("Отменить", f"cancel_task:{task_id}"),
        )
    )


def make_rating_keyboard(transcription_id: int, selected: int | None = None) -> KeyboardBuilder:
    buttons = [
        CallbackButton(
            f"✅ {i}⭐" if i == selected else f"{i}⭐",
            f"rate:{transcription_id}:{i}",
        )
        for i in range(1, 6)
    ]
    return KeyboardBuilder().row(*buttons)


def make_topup_amounts_keyboard() -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(
            CallbackButton("50 ₽", "topup:50"),
            CallbackButton("100 ₽", "topup:100"),
        )
        .row(
            CallbackButton("250 ₽", "topup:250"),
            CallbackButton("500 ₽", "topup:500"),
        )
        .row(CallbackButton("Отменить", "topup:cancel"))
    )


def make_payment_actions_keyboard(order_id: str) -> KeyboardBuilder:
    return (
        KeyboardBuilder()
        .row(CallbackButton("Проверить платёж", f"payment:check:{order_id}"))
        .row(CallbackButton("Отменить платёж", f"payment:cancel:{order_id}"))
    )


def make_summarize_keyboard(transcription_id: int) -> KeyboardBuilder:
    return KeyboardBuilder().row(
        CallbackButton("📝 Создать конспект", f"summarize:{transcription_id}")
    )


def make_send_as_text_keyboard(transcription_id: int) -> KeyboardBuilder:
    return KeyboardBuilder().row(
        CallbackButton("📄 Отправить текстом", f"send_as_text:{transcription_id}")
    )
