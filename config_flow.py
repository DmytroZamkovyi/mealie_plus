"""Config flow: Mealie address and token, options for the sync."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_INTERVAL,
    CONF_PREFIX,
    CONF_PROPAGATE_DELETES,
    CONF_PURGE_DAYS,
    CONF_TOKEN,
    CONF_URL,
    CONF_WEBHOOK_ID,
    DEFAULT_INTERVAL,
    DEFAULT_PREFIX,
    DEFAULT_PROPAGATE_DELETES,
    DEFAULT_PURGE_DAYS,
    DOMAIN,
)
from .mealie import MealieAuthError, MealieClient, MealieError


def _options_schema(opts: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PREFIX, default=opts.get(CONF_PREFIX, DEFAULT_PREFIX)): TextSelector(),
            vol.Required(CONF_INTERVAL, default=opts.get(CONF_INTERVAL, DEFAULT_INTERVAL)): NumberSelector(
                NumberSelectorConfig(min=1, max=120, step=1, unit_of_measurement="min")
            ),
            vol.Required(CONF_PURGE_DAYS, default=opts.get(CONF_PURGE_DAYS, DEFAULT_PURGE_DAYS)): NumberSelector(
                NumberSelectorConfig(min=0, max=60, step=1, unit_of_measurement="d")
            ),
            vol.Required(
                CONF_PROPAGATE_DELETES, default=opts.get(CONF_PROPAGATE_DELETES, DEFAULT_PROPAGATE_DELETES)
            ): BooleanSelector(),
        }
    )


class ShoppingSyncConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, url: str, token: str) -> str | None:
        try:
            await MealieClient(async_get_clientsession(self.hass), url, token).lists()
        except MealieAuthError:
            return "invalid_auth"
        except MealieError:
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            if err := await self._validate(url, user_input[CONF_TOKEN]):
                errors["base"] = err
            else:
                return self.async_create_entry(
                    title="Shopping Sync",
                    data={CONF_URL: url, CONF_TOKEN: user_input[CONF_TOKEN]},
                    options={},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                    vol.Required(CONF_TOKEN): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            if err := await self._validate(entry.data[CONF_URL], user_input[CONF_TOKEN]):
                errors["base"] = err
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: user_input[CONF_TOKEN]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return ShoppingSyncOptionsFlow()


class ShoppingSyncOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_INTERVAL] = int(user_input[CONF_INTERVAL])
            user_input[CONF_PURGE_DAYS] = int(user_input[CONF_PURGE_DAYS])
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self.config_entry.options)),
            description_placeholders={"webhook": f"/api/webhook/{self.config_entry.data.get(CONF_WEBHOOK_ID, '')}"},
        )
