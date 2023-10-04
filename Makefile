## ==========================================================
## ==========================================================
## API Recipes
run-api:    ## Run API
	FLASK_APP=api/maapapp.py flask run --host=0.0.0.0

## ==========================================================
## ==========================================================
## Database Recipes

start-database:	## Start Database
	brew services start postgresql

stop-database:	## Stop Database
	brew services stop postgresql

## ==========================================================
## ==========================================================
## Unit Testing Recipes

test-email: ## Run Tests for Email Utility
	python3 -m unittest test/api/utils/test_email.py

# ----------------------------------------------------------------------------
# Self-Documented Makefile
# ref: http://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
# ----------------------------------------------------------------------------
help:						## (DEFAULT) This help information
	@echo ====================================================================
	@grep -E '^## .*$$'  \
		$(MAKEFILE_LIST)  \
		| awk 'BEGIN { FS="## " }; {printf "\033[33m%-20s\033[0m \n", $$2}'
	@echo
	@grep -E '^[0-9a-zA-Z_-]+:.*?## .*$$'  \
		$(MAKEFILE_LIST)  \
		| awk 'BEGIN { FS=":.*?## " }; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'  \
#		 | sort
.PHONY: help
.DEFAULT_GOAL := help