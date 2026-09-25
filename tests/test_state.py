from datetime import UTC, datetime, timedelta

from glaceon_companion.state import PetState, WAKE_ENERGY_FLOOR


def test_state_advances_and_stays_bounded():
    state = PetState(updated_at=(datetime.now(UTC) - timedelta(hours=10)).isoformat())
    state.advance()
    assert 0 <= state.hunger <= 100
    assert 0 <= state.energy <= 100
    assert state.hunger > 18


def test_interactions_change_expected_needs():
    state = PetState(hunger=80, happiness=20, trust=10)
    state.feed()
    assert state.hunger < 80
    state.pet()
    assert state.happiness > 20
    assert state.trust > 10


def test_direct_interactions_wake_a_sleeping_pet_with_enough_energy_to_stay_awake():
    for interaction in ("feed", "pet", "play", "wake"):
        state = PetState(asleep=True, energy=10)

        getattr(state, interaction)()

        assert state.asleep is False
        assert state.energy >= WAKE_ENERGY_FLOOR


def test_sleep_interaction_remains_asleep():
    state = PetState(asleep=False, energy=50)

    state.sleep()

    assert state.asleep is True


def test_seated_mode_stays_awake_and_recovers_slowly_even_when_exhausted():
    state = PetState(energy=1)
    state.sit()
    start = datetime.fromisoformat(state.updated_at)
    state.advance(start + timedelta(hours=8))
    assert state.seated and not state.asleep
    assert state.energy == 17
    assert state.mood == "sentado"


def test_sitting_wakes_and_explicit_sleep_play_or_resume_exit_mode():
    for command in ('sleep', 'play', 'resume'):
        state = PetState(asleep=True, energy=3)
        state.sit()
        assert state.seated and not state.asleep
        getattr(state, command)()
        assert not state.seated
        assert state.asleep == (command == 'sleep')


def test_food_pet_and_chat_wake_do_not_cancel_sitting():
    state = PetState()
    state.sit()
    for command in ('feed', 'pet', 'wake'):
        getattr(state, command)()
        assert state.seated and not state.asleep
