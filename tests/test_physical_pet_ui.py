from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from glaceon_companion.config import CompanionConfig, ConfigStore
from glaceon_companion.services import CompanionService
from glaceon_companion.ui import PetWindow


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture()
def physical_pet(app, tmp_path):
    store = ConfigStore(tmp_path)
    config = CompanionConfig.defaults()
    config.sound_enabled = False
    config.eevee_companion_enabled = False
    store.save(config)
    service = CompanionService(store, config)
    pet = PetWindow(service, "test-token")
    pet.show()
    app.processEvents()
    yield pet, service
    pet.close()
    service.close()


def test_feed_event_shows_and_consumes_one_berry_without_double_counting(physical_pet):
    pet, service = physical_pet
    before = service.state.hunger

    pet.request_feed()
    pet.poll_events()
    hunger_after_event = service.state.hunger

    assert hunger_after_event < before
    assert pet.interaction_mode == "feeding"
    assert pet.berry_prop.isVisible()

    for _ in range(4):
        pet.advance_feed_sequence()

    assert pet.interaction_mode == "idle"
    assert not pet.berry_prop.isVisible()
    assert service.state.hunger == hunger_after_event


@pytest.mark.parametrize("delta,direction", [((0, -70), 4), ((0, 70), 0), ((70, -70), 3), ((-70, 70), 7)])
def test_two_dimensional_wander_uses_correct_facing_and_arrives(physical_pet, monkeypatch, delta, direction):
    pet, service = physical_pet
    service.state.asleep = False
    pet.move(150, 150)
    monkeypatch.setattr(pet, "_wander_bounds", lambda: (-500, 500, -500, 500))
    monkeypatch.setattr(pet, "_wander_obstacles", lambda: [])
    pet.wander_target, pet.wander_target_y = 150 + delta[0], 150 + delta[1]
    pet.movement_purpose = "wander"
    pet.movement_timer.start()
    pet.move_step()
    assert pet.direction == direction
    assert pet.y() != 150
    for _ in range(100):
        if pet.wander_target is None:
            break
        pet.move_step()
    assert pet.pos() == QPoint(150 + delta[0], 150 + delta[1])
    assert not pet.movement_timer.isActive()


def test_random_wander_can_choose_a_vertical_route(physical_pet, monkeypatch):
    pet, service = physical_pet
    service.state.asleep = False
    pet.move(150, 150)
    monkeypatch.setattr(pet, "_wander_bounds", lambda: (-500, 500, -500, 500))
    monkeypatch.setattr(pet, "_wander_obstacles", lambda: [])
    monkeypatch.setattr("glaceon_companion.ui.random.shuffle", lambda items: None)
    pet.start_wander()
    assert pet.wander_target == pet.x()
    assert pet.wander_target_y > pet.y()
    assert pet.direction == 0


def test_wander_stops_before_new_obstacle_or_screen_edge(physical_pet, monkeypatch):
    from glaceon_companion.codex_presence import ReservedRect

    pet, service = physical_pet
    service.state.asleep = False
    pet.move(150, 150)
    pet.play("Walk", direction=0, loop=True)
    monkeypatch.setattr(pet, "_wander_bounds", lambda: (-500, 500, -500, 500))
    sprite = pet._arfoxia_rect()
    monkeypatch.setattr(pet, "_wander_obstacles", lambda: [ReservedRect(sprite.x, sprite.bottom + 1, 160, 80)])
    pet.wander_target, pet.wander_target_y = 150, 220
    pet.movement_purpose = "wander"
    pet.move_step()
    assert pet.pos() == QPoint(150, 150)
    assert pet.wander_target is None
    monkeypatch.setattr(pet, "_wander_obstacles", lambda: [])
    monkeypatch.setattr(pet, "_wander_bounds", lambda: (0, 150, 0, 150))
    pet.wander_target, pet.wander_target_y = 150, 220
    pet.movement_purpose = "wander"
    pet.move_step()
    assert pet.pos() == QPoint(150, 150)
    assert pet.wander_target_y is None


def test_expressions_repeat_briefly_then_return_to_idle(physical_pet):
    pet, service = physical_pet
    service.state.asleep = False
    assert pet.play_expression("Nod")
    assert pet.expression_cycles_left > 0
    for _ in range(10):
        pet.frame_index = len(pet.frames) - 1
        pet.next_frame()
        if pet.current_animation == "Idle":
            break
    assert pet.current_animation == "Idle"
    assert pet.expression_cycles_left == 0


@pytest.mark.parametrize("mode", ["sleep", "sit", "fetch", "drag"])
def test_expressions_do_not_interrupt_explicit_rest_or_tasks(physical_pet, mode):
    pet, service = physical_pet
    service.state.asleep = mode == "sleep"
    service.state.seated = mode == "sit"
    if mode == "fetch":
        pet.movement_purpose = "fetch"
    if mode == "drag":
        pet.drag_origin = QPoint(10, 10)
    animation = pet.current_animation
    assert not pet.play_expression("Hop")
    assert pet.current_animation == animation


def test_sleep_stops_vertical_movement(physical_pet):
    pet, service = physical_pet
    start = pet.pos()
    pet.wander_target, pet.wander_target_y = pet.x(), pet.y() - 80
    pet.movement_purpose = "wander"
    service.state.asleep = True
    pet.move_step()
    assert pet.pos() == start
    assert pet.wander_target_y is None
    assert pet.current_animation == "Sleep"


def test_automatic_expressions_do_not_repeat_consecutively(physical_pet):
    pet, service = physical_pet
    service.state.asleep = False
    previous = None
    for _ in range(12):
        assert pet.play_expression()
        assert pet.current_animation != previous
        previous = pet.current_animation


def test_negative_monitor_bounds_keep_gestures_visible(physical_pet, monkeypatch):
    from PySide6.QtCore import QRect
    from types import SimpleNamespace

    pet, _ = physical_pet
    screen = QRect(-1920, -1080, 1920, 1040)
    monkeypatch.setattr(pet, "_screen_for_pet", lambda: SimpleNamespace(availableGeometry=lambda: screen))
    left, right, top, bottom = pet._wander_bounds()
    assert left < right and top < bottom
    for x, y in ((left, top), (right, bottom)):
        pet.move(x, y)
        for animation in ("Walk", "Hop", "Wake", "Pose"):
            pet.play(animation, direction=0)
            sprite = pet._arfoxia_rect()
            assert sprite.x >= screen.left()
            assert sprite.right <= screen.right() + 1
            assert sprite.y >= screen.top()
            assert sprite.bottom <= screen.bottom() + 1


def test_expression_menu_has_all_gestures_and_runs_selected_one(physical_pet, monkeypatch):
    from PySide6.QtWidgets import QMenu
    from glaceon_companion.pet_motion import EXPRESSION_LABELS

    pet, service = physical_pet
    service.state.asleep = False
    class TestMenu(QMenu):
        def exec(self, position):
            actions = self.actions()
            submenu = next(action.menu() for action in actions if action.text() == "Expresiones")
            assert submenu.isEnabled()
            assert {action.text() for action in submenu.actions()} == set(EXPRESSION_LABELS.values())
            next(action for action in submenu.actions() if action.text() == "Estirarse").trigger()
    monkeypatch.setattr("glaceon_companion.ui.QMenu", TestMenu)
    pet.open_menu(QPoint(20, 20))
    assert pet.current_animation == "Wake"


def test_lemon_route_ignores_old_vertical_wander_target(physical_pet, monkeypatch):
    pet, service = physical_pet
    service.state.asleep = False
    monkeypatch.setattr(pet, "_eevee_rect", lambda: None)
    pet.move(150, 150)
    pet.wander_target, pet.wander_target_y = 250, 50
    pet.movement_purpose = "fetch"
    pet.move_step()
    assert pet.pos() == QPoint(153, 150)


def test_close_stops_autonomous_and_animation_timers(physical_pet):
    pet, _ = physical_pet
    pet.movement_timer.start()
    pet.close()
    assert not any(timer.isActive() for timer in (
        pet.animation_timer, pet.movement_timer, pet.behavior_timer, pet.event_timer
    ))


def test_sit_stops_movement_and_blocks_automatic_sleep_and_animations(physical_pet):
    pet, service = physical_pet
    pet.start_wander()
    service.interact('sit')
    pet.poll_events()
    position = pet.pos()
    service.state.energy = 1
    pet.autonomous_behavior()
    pet.start_wander()
    pet.move_next_to_eevee()
    pet.move_step()
    service.events.put({'type': 'chat_received', 'has_attachments': True})
    service.events.put({'type': 'action', 'action': 'web_search'})
    pet.poll_events()
    pet.frame_index = len(pet.frames) - 1
    pet.next_frame()
    assert pet.pos() == position
    assert not pet.movement_timer.isActive()
    assert pet.wander_target is None
    assert pet.current_animation == 'Sit'
    assert not service.state.asleep
    service.interact('resume')
    pet.poll_events()
    pet.start_wander()
    assert pet.movement_timer.isActive()


@pytest.mark.parametrize('activity', ['food', 'lemon'])
def test_sit_cancels_active_props_and_keeps_awake(physical_pet, activity):
    pet, service = physical_pet
    if activity == 'food':
        pet.request_feed()
        pet.poll_events()
    else:
        pet.begin_fetch_game()
    service.interact('sit')
    pet.poll_events()
    assert pet.interaction_mode == 'idle'
    assert not pet.berry_prop.isVisible()
    assert not pet.lemon_prop.isVisible()
    assert not pet.placement_overlay.isVisible()
    assert not pet.feed_timer.isActive()
    assert pet.current_animation == 'Sit'


def test_food_finishes_seated_but_explicit_lemon_exits_mode(physical_pet):
    pet, service = physical_pet
    service.interact('sit')
    pet.poll_events()
    pet.request_feed()
    pet.poll_events()
    for _ in range(4):
        pet.advance_feed_sequence()
    assert pet.current_animation == 'Sit'
    assert service.state.seated
    pet.begin_fetch_game()
    pet.poll_events()
    assert not service.state.seated
    assert pet.interaction_mode == 'aiming_lemon'


def test_seated_sprite_restored_on_restart(app, tmp_path):
    store = ConfigStore(tmp_path)
    config = store.load()
    config.eevee_companion_enabled = False
    service = CompanionService(store, config)
    service.interact('sit')
    pet = PetWindow(service, 'token')
    try:
        assert pet.current_animation == 'Sit'
        assert not service.state.asleep
    finally:
        pet.close()
        service.close()


def test_dragging_seated_pet_over_bed_does_not_make_it_sleep(physical_pet, monkeypatch):
    pet, service = physical_pet
    service.interact('sit')
    pet.poll_events()
    pet.bed_prop.show()
    pet.pet_distance = 20
    monkeypatch.setattr('glaceon_companion.ui.foot_is_over_bed', lambda *args: True)
    pet.mouseReleaseEvent(None)
    assert service.state.seated and not service.state.asleep
    assert not pet.sleeping_on_bed


def test_desktop_menu_can_toggle_sitting(physical_pet, monkeypatch):
    from PySide6.QtWidgets import QMenu
    pet, service = physical_pet
    selected_labels = []
    def choose(menu, position):
        label = 'Volver a pasear' if service.state.seated else 'Quedarse sentado (sin dormir)'
        action = next(item for item in menu.actions() if item.text() == label)
        selected_labels.append(label)
        action.trigger()
    class TestMenu(QMenu):
        def exec(self, position):
            choose(self, position)
    monkeypatch.setattr('glaceon_companion.ui.QMenu', TestMenu)
    pet.open_menu(QPoint(20, 20))
    pet.poll_events()
    assert service.state.seated
    pet.open_menu(QPoint(20, 20))
    pet.poll_events()
    assert not service.state.seated
    assert len(selected_labels) == 2


def test_lemon_is_returned_before_play_reward_is_applied(app, physical_pet, monkeypatch):
    pet, service = physical_pet
    fake_cursor = type("FakeCursor", (), {"pos": staticmethod(lambda: QPoint(740, 400))})
    monkeypatch.setattr("glaceon_companion.ui.QCursor", fake_cursor)
    service.state.happiness = 50
    service.database.save_state(service.state)

    pet.begin_fetch_game()
    pet.placement_overlay.finish(QPoint(220, 420))
    pet.lemon_flight.setCurrentTime(pet.lemon_flight.duration())
    app.processEvents()

    assert pet.interaction_mode == "fetching"
    assert service.state.happiness == 50
    pet.move(pet.wander_target, pet.y())
    pet.move_step()
    assert pet.interaction_mode == "returning"
    assert service.state.happiness == 50
    pet.move(pet.wander_target, pet.y())
    pet.move_step()

    assert pet.interaction_mode == "idle"
    assert service.state.happiness == 63
    assert not pet.lemon_prop.isVisible()
    pet.poll_events()
    assert service.state.happiness == 63


def test_escape_cancels_lemon_preview_and_releases_overlay(app, physical_pet):
    pet, _ = physical_pet

    pet.begin_fetch_game()
    assert pet.placement_overlay.isVisible()
    assert pet.placement_overlay.mode == "lemon"

    QTest.keyClick(pet.placement_overlay, Qt.Key.Key_Escape)
    app.processEvents()

    assert pet.interaction_mode == "idle"
    assert not pet.placement_overlay.isVisible()
    assert pet.placement_overlay.mode == ""
    assert not pet.placement_overlay.preview_timer.isActive()
    assert not pet.placement_overlay.timeout.isActive()


def test_bed_and_lemon_previews_follow_the_pointer(app, physical_pet):
    pet, _ = physical_pet
    overlay = pet.placement_overlay
    original_cursor = QCursor.pos()
    try:
        pet.begin_bed_placement()
        bed_point = QPoint(180, 260)
        QCursor.setPos(overlay.mapToGlobal(bed_point))
        QTest.qWait(40)
        app.processEvents()

        assert overlay.preview_center == bed_point
        assert not overlay.preview_pixmap.isNull()
        assert overlay.cursor().shape() == Qt.CursorShape.BlankCursor

        QTest.keyClick(overlay, Qt.Key.Key_Escape)
        app.processEvents()
        pet.begin_fetch_game()
        lemon_point = QPoint(420, 340)
        QCursor.setPos(overlay.mapToGlobal(lemon_point))
        QTest.qWait(40)
        app.processEvents()

        assert overlay.preview_center == lemon_point
        assert not overlay.preview_pixmap.isNull()
        assert overlay.cursor().shape() == Qt.CursorShape.BlankCursor

        QTest.keyClick(overlay, Qt.Key.Key_Escape)
        app.processEvents()
    finally:
        if overlay.mode:
            overlay.cancel()
        QCursor.setPos(original_cursor)


def test_overlay_click_places_bed_at_the_visible_preview(app, physical_pet):
    pet, service = physical_pet
    overlay = pet.placement_overlay
    pet.begin_bed_placement()
    local_point = QPoint(360, 420)
    global_point = overlay.mapToGlobal(local_point)

    QTest.mouseClick(
        overlay,
        Qt.MouseButton.LeftButton,
        pos=local_point,
    )
    app.processEvents()

    bed = pet.bed_prop.screen_rect()
    assert pet.interaction_mode == "idle"
    assert not overlay.isVisible()
    assert bed.x + bed.width // 2 == global_point.x()
    assert bed.y + bed.height // 2 == global_point.y()
    assert service.config.bed_enabled is True


def test_bed_can_be_dragged_directly_and_restores_its_position(app, physical_pet):
    pet, service = physical_pet
    service.config.bed_enabled = True
    service.config.bed_screen_name = QApplication.primaryScreen().name()
    service.config.bed_x_ratio = 0.9604395604395605
    service.config.bed_y_ratio = 0.0
    service.store.save(service.config)
    pet.restore_bed()
    bed = pet.bed_prop
    original = bed.pos()
    local_start = QPoint(bed.width() // 2, bed.height() // 2)
    delta = QPoint(-140, 90)

    QTest.mousePress(
        bed,
        Qt.MouseButton.LeftButton,
        pos=local_start,
    )
    QTest.mouseMove(bed, local_start + delta)
    QTest.mouseRelease(
        bed,
        Qt.MouseButton.LeftButton,
        pos=local_start + delta,
    )
    app.processEvents()

    expected = original + delta
    assert bed.pos() == expected
    assert not (
        bed.windowFlags() & Qt.WindowType.WindowTransparentForInput
    )
    assert (
        pet.lemon_prop.windowFlags()
        & Qt.WindowType.WindowTransparentForInput
    )
    saved_ratios = (
        service.config.bed_x_ratio,
        service.config.bed_y_ratio,
    )
    assert saved_ratios != (0.9604395604395605, 0.0)

    bed.move(0, 0)
    pet.restore_bed()

    assert bed.pos() == expected
    assert (
        service.config.bed_x_ratio,
        service.config.bed_y_ratio,
    ) == saved_ratios


def test_moving_bed_while_sleeping_keeps_arfoxia_attached(physical_pet):
    pet, service = physical_pet
    pet.place_bed(QPoint(300, 500))
    pet.sleep_on_bed()
    pet.place_bed(QPoint(650, 300))

    bed = pet.bed_prop.screen_rect()
    target_x = bed.x + bed.width // 2 - pet.width() // 2
    target_y = bed.y + round(bed.height * 0.72) - pet.height() + 12
    assert service.state.asleep is True
    assert pet.sleeping_on_bed is True
    assert pet.pos() == QPoint(target_x, target_y)


def test_drag_drop_over_persistent_bed_puts_arfoxia_to_sleep(physical_pet):
    pet, service = physical_pet
    pet.place_bed(QPoint(430, 520))
    bed = pet.bed_prop.screen_rect()
    target_foot_y = bed.y + bed.height // 2
    pet.move(
        bed.x + bed.width // 2 - pet.width() // 2,
        target_foot_y - pet.height() + 12,
    )
    pet.pet_distance = 20

    pet.mouseReleaseEvent(None)

    assert service.state.asleep is True
    assert pet.sleeping_on_bed is True
    assert pet.current_animation == "Sleep"
    assert service.config.bed_enabled is True


def test_reloaded_low_energy_arfoxia_wakes_on_click_and_stays_awake(
    app, tmp_path, monkeypatch
):
    store = ConfigStore(tmp_path)
    config = CompanionConfig.defaults()
    config.sound_enabled = False
    config.eevee_companion_enabled = False
    store.save(config)
    seeded_service = CompanionService(store, config)
    seeded_service.state.energy = 10
    seeded_service.state.sleep()
    seeded_service.database.save_state(seeded_service.state)
    seeded_service.close()

    service = CompanionService(store, config)
    pet = PetWindow(service, "test-token")
    pet.show()
    app.processEvents()
    try:
        assert service.state.asleep is True
        assert pet.current_animation == "Sleep"

        sprite = pet._arfoxia_rect()
        click_position = QPoint(
            sprite.x - pet.x() + sprite.width // 2,
            sprite.y - pet.y() + sprite.height // 2,
        )
        QTest.mouseClick(
            pet,
            Qt.MouseButton.LeftButton,
            pos=click_position,
        )
        app.processEvents()
        pet.poll_events()

        assert service.state.asleep is False
        assert pet.current_animation == "Wake"

        monkeypatch.setattr("glaceon_companion.ui.random.random", lambda: 1.0)
        pet.autonomous_behavior()

        assert service.state.asleep is False
        assert pet.current_animation != "Sleep"
    finally:
        pet.close()
        service.close()


def test_remote_authorization_releases_lemon_keyboard_overlay(physical_pet, monkeypatch):
    pet, service = physical_pet
    requested = []
    monkeypatch.setattr(
        pet.chat_window,
        "request_authorization",
        lambda challenge_id, summary, configured, **kwargs: requested.append(
            (challenge_id, summary, configured, kwargs.get("auto_prompt"))
        ),
    )
    pet.begin_fetch_game()
    assert pet.placement_overlay.isVisible()
    assert pet.interaction_mode == "aiming_lemon"

    service.events.put(
        {
            "type": "authorization_requested",
            "challenge_id": "test-challenge",
            "summary": "Reiniciar el PC",
            "password_configured": True,
        }
    )
    pet.poll_events()

    assert not pet.placement_overlay.isVisible()
    assert pet.interaction_mode == "idle"
    assert not pet.quick_chat.isVisible()
    assert not pet.speech_bubble.isVisible()
    assert requested == [("test-challenge", "Reiniciar el PC", True, False)]


def test_remote_show_chat_event_opens_the_full_minimizable_window(
    physical_pet,
    monkeypatch,
):
    pet, service = physical_pet
    opened = []
    monkeypatch.setattr(pet, "show_chat", lambda: opened.append("full"))
    monkeypatch.setattr(
        pet,
        "show_quick_chat",
        lambda: pytest.fail("No debe abrir la entrada compacta"),
    )

    service.events.put({"type": "ui", "action": "show_chat"})
    pet.poll_events()

    assert opened == ["full"]


def test_received_chat_sits_and_stops_only_autonomous_wandering(physical_pet):
    pet, service = physical_pet
    pet.wander_target = pet.x() + 200
    pet.movement_purpose = "wander"
    pet.play("Walk", loop=True)
    pet.movement_timer.start()

    service.events.put({"type": "chat_received"})
    pet.poll_events()

    assert pet.current_animation == "Sit"
    assert pet.loop_animation is False
    assert pet.wander_target is None
    assert pet.movement_purpose == "idle"
    assert not pet.movement_timer.isActive()


def test_received_chat_does_not_wake_sleeping_arfoxia(physical_pet):
    pet, service = physical_pet
    service.state.sleep()
    service.database.save_state(service.state)
    pet.play("Sleep", loop=True)

    service.events.put({"type": "chat_received"})
    pet.poll_events()

    assert service.state.asleep is True
    assert pet.current_animation == "Sleep"
    assert pet.loop_animation is True


def test_received_chat_does_not_interrupt_lemon_fetch(physical_pet):
    pet, service = physical_pet
    target = pet.x() + 180
    pet.interaction_mode = "fetching"
    pet.movement_purpose = "fetch"
    pet.wander_target = target
    pet.play("Walk", direction=2, loop=True)
    pet.movement_timer.start()

    service.events.put({"type": "chat_received"})
    pet.poll_events()

    assert pet.interaction_mode == "fetching"
    assert pet.movement_purpose == "fetch"
    assert pet.wander_target == target
    assert pet.current_animation == "Walk"
    assert pet.movement_timer.isActive()
