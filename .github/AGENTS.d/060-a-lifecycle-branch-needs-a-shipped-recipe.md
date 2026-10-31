## A lifecycle branch needs a shipped recipe, not a prototype

The rollback path, its env injection and 125 lines of tests ran only against synthetic prototypes because zero of 520 recipes declared `rollback:`; ship a recipe that uses a lifecycle phase before adding the phase.
