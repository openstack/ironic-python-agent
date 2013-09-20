CODEDIR=teeth_agent
SCRIPTSDIR=scripts

UNITTESTS ?= ${CODEDIR}
PYTHONLINT=${SCRIPTSDIR}/python-lint.py
PYDIRS=${CODEDIR} ${SCRIPTSDIR}

test: unit

unit:
ifneq ($(JENKINS_URL), )
	trial --random 0 --reporter=subunit ${UNITTESTS} | tee subunit-output.txt
	tail -n +3 subunit-output.txt | subunit2junitxml > test-report.xml
else
	trial --random 0 ${UNITTESTS}
endif

env:
	./scripts/bootstrap-virtualenv.sh

lint:
	${PYTHONLINT} ${PYDIRS}

clean:
	find . -name '*.pyc' -delete
	find . -name '.coverage' -delete
	find . -name '_trial_coverage' -print0 | xargs --null rm -rf
	find . -name '_trial_temp' -print0 | xargs --null rm -rf
	rm -rf dist build *.egg-info

