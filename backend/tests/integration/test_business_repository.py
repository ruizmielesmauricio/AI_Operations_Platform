"""Covers app/repositories/business.py's one-shop-per-account limit and
soft-delete behavior against a real (SQLite) database — the parts too
stateful/DB-dependent to be pure unit tests.
"""

import pytest

from app.models.business import Business
from app.models.membership import Membership
from app.models.product import Product
from app.repositories.business import (
    BusinessLimitReached,
    NotBusinessOwner,
    count_owned_standalone_businesses,
    create_branch_business,
    create_business_with_owner,
    list_businesses_for_user,
    soft_delete_business,
    update_business_profile,
)


def test_count_owned_standalone_businesses_is_zero_for_a_fresh_user(db_session):
    assert count_owned_standalone_businesses(db_session, user_id="user-a") == 0


def test_create_business_with_owner_succeeds_for_the_first_business(db_session):
    business = create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    assert business.name == "Shop A"
    assert count_owned_standalone_businesses(db_session, user_id="user-a") == 1


def test_create_business_with_owner_rejects_a_second_standalone_business(db_session):
    create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )

    with pytest.raises(BusinessLimitReached):
        create_business_with_owner(
            db_session, name="Shop A2", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
        )

    # The rejected attempt must not have partially created anything.
    assert count_owned_standalone_businesses(db_session, user_id="user-a") == 1


def test_a_branch_does_not_count_toward_the_standalone_limit(db_session):
    # Schema groundwork only — no route creates a branch yet, so this
    # sets parent_business_id directly, the same way a future branch-
    # creation feature would. Confirms count_owned_standalone_businesses
    # correctly excludes it rather than treating it as a second
    # standalone shop (which would either wrongly free up a slot or
    # wrongly consume one).
    primary = create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    branch = Business(name="Shop A Branch", parent_business_id=primary.id)
    db_session.add(branch)
    db_session.flush()
    db_session.add(Membership(business_id=branch.id, user_id="user-a", role="owner"))
    db_session.commit()

    assert count_owned_standalone_businesses(db_session, user_id="user-a") == 1

    # And the limit is still correctly enforced — the branch didn't
    # accidentally free up (or consume an extra) standalone slot.
    with pytest.raises(BusinessLimitReached):
        create_business_with_owner(
            db_session, name="Shop A3", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
        )


def test_list_businesses_for_user_excludes_soft_deleted_businesses(db_session):
    business = create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    assert len(list_businesses_for_user(db_session, user_id="user-a")) == 1

    soft_delete_business(db_session, business=business)

    assert list_businesses_for_user(db_session, user_id="user-a") == []
    # And a new standalone business can now be created — the deleted one
    # no longer counts against the limit.
    create_business_with_owner(
        db_session, name="Shop A New", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )


def test_list_businesses_for_user_with_include_deleted_shows_archived_ones_too(db_session):
    business = create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    soft_delete_business(db_session, business=business)

    # Default behavior (every other caller) is unchanged — still excluded.
    assert list_businesses_for_user(db_session, user_id="user-a") == []

    # Opt-in surfaces it again, deleted_at intact, for the one caller that
    # explicitly wants to show archived businesses (status "Deleted").
    rows = list_businesses_for_user(db_session, user_id="user-a", include_deleted=True)
    assert len(rows) == 1
    assert rows[0][0].name == "Shop A"
    assert rows[0][0].deleted_at is not None


def test_soft_delete_business_does_not_touch_any_child_rows(db_session):
    # The real guarantee this whole soft-delete design exists for:
    # archiving a business must never destroy its financial/audit data.
    business = create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    product = Product(business_id=business.id, name="Chain Lube", sku="CL-100")
    db_session.add(product)
    db_session.commit()
    product_id = product.id

    soft_delete_business(db_session, business=business)

    # Still directly queryable by id — nothing cascaded.
    still_there = db_session.get(Product, product_id)
    assert still_there is not None
    assert still_there.name == "Chain Lube"
    assert db_session.get(Business, business.id).deleted_at is not None


# --- create_branch_business ------------------------------------------------


def test_create_branch_business_succeeds_for_the_parent_s_owner(db_session):
    primary = create_business_with_owner(
        db_session, name="Text Bike Shop", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    branch = create_branch_business(
        db_session, name="Test Shop", template="bicycle_shop", timezone="Europe/Dublin",
        owner_user_id="user-a", parent_business_id=primary.id,
    )
    assert branch.parent_business_id == primary.id


def test_create_branch_business_does_not_count_toward_the_standalone_limit(db_session):
    # The real point of the whole feature: adding a branch must never
    # trip the one-standalone-shop limit for its owner.
    primary = create_business_with_owner(
        db_session, name="Text Bike Shop", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    create_branch_business(
        db_session, name="Test Shop", template="bicycle_shop", timezone="Europe/Dublin",
        owner_user_id="user-a", parent_business_id=primary.id,
    )
    assert count_owned_standalone_businesses(db_session, user_id="user-a") == 1


def test_create_branch_business_rejects_a_non_owner_of_the_parent(db_session):
    primary = create_business_with_owner(
        db_session, name="Text Bike Shop", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    with pytest.raises(NotBusinessOwner):
        create_branch_business(
            db_session, name="Test Shop", template="bicycle_shop", timezone="Europe/Dublin",
            owner_user_id="user-b", parent_business_id=primary.id,
        )


def test_create_branch_business_rejects_a_manager_of_the_parent_not_just_strangers(db_session):
    # A manager/staff membership on the parent must not be enough to add
    # a branch — only its owner.
    primary = create_business_with_owner(
        db_session, name="Text Bike Shop", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    db_session.add(Membership(business_id=primary.id, user_id="user-b", role="manager"))
    db_session.commit()

    with pytest.raises(NotBusinessOwner):
        create_branch_business(
            db_session, name="Test Shop", template="bicycle_shop", timezone="Europe/Dublin",
            owner_user_id="user-b", parent_business_id=primary.id,
        )


# --- update_business_profile -------------------------------------------


def test_update_business_profile_writes_only_whitelisted_fields(db_session):
    business = create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    updated = update_business_profile(
        db_session,
        business=business,
        updates={
            "manager_name": "Aoife Byrne",
            "contact_email": "aoife@shopa.example",
            "city": "Dublin",
            # Not a real profile field — deliberately included to prove
            # the defensive whitelist actually ignores it rather than
            # raising or silently writing a bogus attribute.
            "name": "Renamed via the back door",
        },
    )
    assert updated.manager_name == "Aoife Byrne"
    assert updated.contact_email == "aoife@shopa.example"
    assert updated.city == "Dublin"
    assert updated.name == "Shop A"


def test_update_business_profile_can_explicitly_clear_a_field(db_session):
    business = create_business_with_owner(
        db_session, name="Shop A", template="bicycle_shop", timezone="Europe/Dublin", owner_user_id="user-a"
    )
    update_business_profile(db_session, business=business, updates={"manager_name": "Aoife Byrne"})

    cleared = update_business_profile(db_session, business=business, updates={"manager_name": None})
    assert cleared.manager_name is None
