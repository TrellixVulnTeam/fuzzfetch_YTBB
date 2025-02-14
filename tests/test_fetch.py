"""fuzzfetch tests"""
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import itertools
import logging
import time
from datetime import datetime

import pytest  # pylint: disable=import-error
from freezegun import freeze_time  # pylint: disable=import-error

import fuzzfetch

LOG = logging.getLogger("fuzzfetch_test")
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("flake8").setLevel(logging.WARNING)


def get_builds_to_test():
    """Get permutations for testing build branches and flags"""
    possible_flags = (
        # opt
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=False,
            debug=False,
            fuzzing=False,
            coverage=False,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # debug
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=False,
            debug=True,
            fuzzing=False,
            coverage=False,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # ccov
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=False,
            debug=False,
            fuzzing=False,
            coverage=True,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # asan-opt
        fuzzfetch.BuildFlags(
            asan=True,
            tsan=False,
            debug=False,
            fuzzing=False,
            coverage=False,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # asan-opt-fuzzing
        fuzzfetch.BuildFlags(
            asan=True,
            tsan=False,
            debug=False,
            fuzzing=True,
            coverage=False,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # tsan-opt
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=True,
            debug=False,
            fuzzing=False,
            coverage=False,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # tsan-opt-fuzzing
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=True,
            debug=False,
            fuzzing=True,
            coverage=False,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # debug-fuzzing
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=False,
            debug=True,
            fuzzing=True,
            coverage=False,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # ccov-fuzzing
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=False,
            debug=False,
            fuzzing=True,
            coverage=True,
            valgrind=False,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
        # valgrind-opt
        fuzzfetch.BuildFlags(
            asan=False,
            tsan=False,
            debug=False,
            fuzzing=False,
            coverage=False,
            valgrind=True,
            no_opt=False,
            fuzzilli=False,
            nyx=False,
        ),
    )
    possible_branches = ("central", "try", "esr-next", "esr-stable")
    possible_os = ("Android", "Darwin", "Linux", "Windows")
    possible_cpus = ("x86", "x64", "arm", "arm64")

    for branch, flags, os_, cpu in itertools.product(
        possible_branches, possible_flags, possible_os, possible_cpus
    ):
        try:
            fuzzfetch.Platform(os_, cpu)
        except fuzzfetch.FetcherException:
            continue
        if flags.coverage and (os_ != "Linux" or cpu != "x64" or branch != "central"):
            # coverage builds not done for android/macos/windows
            # coverage builds are only done on central
            continue
        if flags.asan and cpu != "x64":
            continue
        if flags.tsan and (cpu != "x64" or os_ != "Linux"):
            continue
        if flags.tsan and branch.startswith("esr"):
            continue
        if flags.debug and flags.fuzzing and os_ == "Windows" and cpu == "x64":
            continue
        if flags.debug and flags.fuzzing and os_ == "Darwin":
            continue
        if flags.debug and flags.fuzzing and os_ == "Linux" and cpu == "x86":
            continue
        if flags.valgrind and (os_ != "Linux" or cpu != "x64"):
            continue
        if os_ == "Darwin" and flags.asan and not flags.fuzzing:
            continue
        if os_ == "Android" and flags.debug and not flags.fuzzing and cpu != "arm":
            continue
        if (
            os_ == "Android"
            and flags.fuzzing
            and (cpu != "x86" or flags.asan or not flags.debug)
        ):
            continue
        if os_ == "Android" and not flags.fuzzing and flags.asan:
            continue
        if os_ == "Windows" and flags.asan and branch != "central":
            # asan builds for windows are only done for central
            continue
        if os_ == "Windows" and flags.asan and (flags.fuzzing or flags.debug):
            # windows only has asan-opt ?
            continue
        if os_ == "Windows" and cpu != "x64" and (flags.asan or flags.fuzzing):
            # windows asan and fuzzing builds are x64 only atm
            continue
        if os_ == "Android" and branch in {"esr-next", "esr-stable"}:
            continue
        if not all(flags) and branch.startswith("esr"):
            # opt builds aren't available for esr
            continue
        if branch == "esr-stable":
            if cpu.startswith("arm"):
                # arm builds aren't available for esr-stable
                continue

        yield pytest.param(branch, flags, os_, cpu)


@pytest.mark.parametrize("branch, build_flags, os_, cpu", get_builds_to_test())
@pytest.mark.usefixtures("requests_mock_cache")
def test_metadata(branch, build_flags, os_, cpu):
    """Instantiate a Fetcher (which downloads metadata from TaskCluster) and check that
    the build is recent.
    """
    # BuildFlags(asan, debug, fuzzing, coverage, valgrind)
    # Fetcher(branch, build, flags, arch_32)
    # Set freeze_time to a date ahead of the latest mock build
    platform_ = fuzzfetch.Platform(os_, cpu)
    for as_args in (True, False):  # try as API and as command line
        if as_args:
            args = [
                f"--{name}"
                for arg, name in zip(build_flags, fuzzfetch.BuildFlags._fields)
                if arg
            ]
            fetcher = fuzzfetch.Fetcher.from_args(
                [f"--{branch}", "--cpu", cpu, "--os", os_] + args
            )[0]
        else:
            if branch.startswith("esr"):
                branch = fuzzfetch.Fetcher.resolve_esr(branch)
            fetcher = fuzzfetch.Fetcher(branch, "latest", build_flags, platform_)

        LOG.debug("succeeded creating Fetcher")
        LOG.debug("buildid: %s", fetcher.id)
        LOG.debug("hgrev: %s", fetcher.changeset)

        time_obj = time.strptime(fetcher.id, "%Y%m%d%H%M%S")

        # yyyy-mm-dd is also accepted as a build input
        date_str = f"{time_obj.tm_year:d}-{time_obj.tm_mon:02d}-{time_obj.tm_mday:02d}"
        if as_args:
            fuzzfetch.Fetcher.from_args(
                [f"--{branch}", "--cpu", cpu, "--os", os_, "--build", date_str] + args
            )
        else:
            fuzzfetch.Fetcher(branch, date_str, build_flags, platform_)

        # hg rev is also accepted as a build input
        rev = fetcher.changeset
        if as_args:
            fuzzfetch.Fetcher.from_args(
                [f"--{branch}", "--cpu", cpu, "--os", os_, "--build", rev] + args
            )
        else:
            fuzzfetch.Fetcher(branch, rev, build_flags, platform_)
        # namespace = fetcher.build

        # TaskCluster namespace is also accepted as a build input
        # namespace = ?
        # fuzzfetch.Fetcher(branch, namespace,
        #                   (asan, debug, fuzzing, coverage))


# whenever BUILD_CACHE is set:
# - requested should be set to the near future, or the hg hash of a changeset prior to
#   the first build yesterday
# - expected should be updated to the value that asserts
@pytest.mark.parametrize(
    "requested, expected, direction",
    (
        ("2020-06-06", "2020-06-09", fuzzfetch.BuildSearchOrder.ASC),
        ("2021-06-09", "2021-06-08", fuzzfetch.BuildSearchOrder.DESC),
        (
            "32fba417ebd01dfb2c2a392cdb1fad7ef66e96e8",
            "7f7b983390650cbc7d736e92fd3e1f629a30ac02",
            fuzzfetch.BuildSearchOrder.ASC,
        ),
    ),
)
@pytest.mark.parametrize("is_namespace", [True, False])
@pytest.mark.usefixtures("requests_mock_cache")
def test_nearest_retrieval(requested, expected, direction, is_namespace):
    """
    Attempt to retrieve a build near the supplied build_id
    """
    flags = fuzzfetch.BuildFlags(
        asan=False,
        tsan=False,
        debug=False,
        fuzzing=False,
        coverage=False,
        valgrind=False,
        no_opt=False,
        fuzzilli=False,
        nyx=False,
    )

    # Set freeze_time to a date ahead of the latest mock build
    with freeze_time("2021-06-08"):
        LOG.debug("looking for nearest to %s", requested)
        if is_namespace:
            if fuzzfetch.BuildTask.RE_DATE.match(requested):
                date = requested.replace("-", ".")
                build_id = (
                    f"gecko.v2.mozilla-central.pushdate.{date}.firefox.linux64-opt"
                )
            else:
                build_id = (
                    f"gecko.v2.mozilla-central.revision.{requested}.firefox.linux64-opt"
                )
        else:
            build_id = requested

        build = fuzzfetch.Fetcher("central", build_id, flags, nearest=direction)
        if fuzzfetch.BuildTask.RE_DATE.match(expected):
            build_date = datetime.strftime(build.datetime, "%Y-%m-%d")
            assert build_date == expected
        else:
            assert fuzzfetch.BuildTask.RE_REV.match(expected)
            assert build.changeset == expected


@pytest.mark.usefixtures("requests_mock_cache")
def test_hash_resolution():
    """
    Test shortened hashes are resolved
    """
    flags = fuzzfetch.BuildFlags(
        asan=False,
        tsan=False,
        debug=False,
        fuzzing=False,
        coverage=False,
        valgrind=False,
        no_opt=False,
        fuzzilli=False,
        nyx=False,
    )
    rev = "24938c537a55f9db3913072d33b178b210e7d6b5"
    build = fuzzfetch.Fetcher("central", rev[:12], flags)
    assert build.changeset == rev


@pytest.mark.usefixtures("requests_mock_cache")
def test_fuzzilli_builds():
    """
    One-off test for retrieving fuzzilli enabled builds
    """
    flags = fuzzfetch.BuildFlags(
        asan=False,
        tsan=False,
        debug=True,
        fuzzing=False,
        coverage=False,
        valgrind=False,
        no_opt=False,
        fuzzilli=True,
        nyx=False,
    )
    fuzzfetch.Fetcher("central", "latest", flags)


@pytest.mark.usefixtures("requests_mock_cache")
def test_nyx_builds():
    """
    Test for retrieving Nyx snapshot enabled builds
    """
    flags = fuzzfetch.BuildFlags(
        asan=True,
        tsan=False,
        debug=False,
        fuzzing=True,
        coverage=False,
        valgrind=False,
        no_opt=False,
        fuzzilli=False,
        nyx=True,
    )
    fuzzfetch.Fetcher("central", "latest", flags)
