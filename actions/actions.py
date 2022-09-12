

from typing import Any, Text, Dict, List

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
import pandas as pd
import logging
from actions.custom_forms import CustomFormValidationAction
from rasa_sdk.events import (
    SlotSet,
    EventType,
    ActionExecuted,
    FollowupAction,
    UserUtteranceReverted,
)
import pathlib
import ruamel.yaml

logger =  logging.getLogger(__name__)


here = pathlib.Path(__file__).parent.absolute()
custom_forms_config = (
    ruamel.yaml.safe_load(open(f"{here}/custom_forms_configs.yml", "r")) or {}).get("custom_forms", {})

MAX_VALIDATION_FAILURES = custom_forms_config.get("max_validation_failures", 2)

cards_db_file_name = './card_db/cards_data.xlsx'
cards = pd.read_excel(cards_db_file_name)

NEXT_FORM_NAME = {
    "temporary_block_intimation": "card_status_update_form",
    "check_balance": "balance_inquiry_form",
}


FORM_DESCRIPTION = {
    "card_status_update_form": "Temporary block on card",
    "balance_inquiry_form": "Balance Inquiry",
}

class ActionCardStatusUpdate(Action):
    def name(self) -> Text:

        return "action_card_status_update"

    def run(self , dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        slots = {
            "AA_CONTINUE_FORM": None,
        }
        slots["AA_CONTINUE_FORM"] = tracker.get_slot("AA_CONTINUE_FORM")
        slots["card_number"] = tracker.get_slot("card_number")
        if (tracker.get_slot("user_authenticated")) and (slots["AA_CONTINUE_FORM"]):
            card_number = slots["card_number"]
            card_present = len(cards[cards['Cards'] == card_number]['Status'])
            if card_present:
                dispatcher.utter_message(template="utter_empathy_for_card_loss")
                status = cards[cards['Cards'] == card_number]['Status'].values[0]
                if status == 'Activated':
                    cards.loc[cards['Cards'] == card_number , 'Status'] = 'Blocked'
                    cards.to_excel(cards_db_file_name, index = False)
                    dispatcher.utter_message(text="Your cards has been temporarily blocked")
                else:
                    dispatcher.utter_message(text= "Your card is already blocked" )
            else:
                dispatcher.utter_message(text="No record found against this Card number")
        return [SlotSet(slot, None) for slot, value in slots.items()]


class ActionBalanceInquiry(Action):
    def name(self) -> Text:

        return "action_balance_inquiry"

    def run(self , dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:
        slots = {
            "AA_CONTINUE_FORM": None,

        }
        slots["AA_CONTINUE_FORM"] = tracker.get_slot("AA_CONTINUE_FORM")
        if (tracker.get_slot("user_authenticated")) and (slots["AA_CONTINUE_FORM"]):
            SSN = eval(tracker.get_slot("SSN"))
            last_four_of_card = tracker.get_slot("last4ofcard")
            record_present = len(cards[(cards['last_4_of_SSN'] == SSN) & (cards['Last_4_of_card'] == last_four_of_card )])
            if record_present:
                if cards[(cards['last_4_of_SSN'] == SSN) & (cards['Last_4_of_card'] == last_four_of_card )]['Status'].values[0] == "Blocked":
                    dispatcher.utter_message("Selected card is blocked, unable to share balance")
                else:
                    balance = cards[(cards['last_4_of_SSN'] == SSN) & (cards['Last_4_of_card'] == last_four_of_card )]['Account_Balance'].values[0]
                    dispatcher.utter_message(text= "Your Balance is {}$".format(balance))
            else:
                dispatcher.utter_message(text="No Cards available against provided SSN")
        events = []
        events.append(SlotSet("last4ofcard" , None))
        events.append(SlotSet("AA_CONTINUE_FORM", None))
        active_form_name = tracker.active_loop.get("name")
        if active_form_name:
            # keep the tracker clean for the predictions with form switch stories
            events.append(UserUtteranceReverted())
            # avoid that bot goes in listen mode after UserUtteranceReverted
            events.append(FollowupAction(active_form_name))

        return events


class ActionAskLastFourOfCard(Action):
    def name(self) -> Text:
        """Unique identifier of the form"""
        return "action_ask_last4ofcard"

    def run(self , dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List[EventType]:

        SSN = eval(tracker.get_slot("SSN"))
        record_present = len(cards[cards['last_4_of_SSN'] == SSN])
        if record_present:
            card_numbers = cards[cards['last_4_of_SSN'] == SSN]['Last_4_of_card'].values
            card_numbers = [str(x) for x in card_numbers]
            dispatcher.utter_message(
                text=f"We have founds these cards (last 4 digits) against your SSN",
                buttons=[{"title": p, "payload": p} for p in card_numbers],
            )
        else:
            dispatcher.utter_message(text= "No Cards available against provided SSN")

        return []

class ValidateCardStatusUpdateForm(CustomFormValidationAction):



    def name(self) -> Text:
        """Unique identifier of the form"""
        return "validate_card_status_update_form"

    async def validate_user_authenticated(self, value: Any , dispatcher: CollectingDispatcher , tracker: Tracker ,
                                             domain: Dict[Text, Any]) -> Dict[Text, Any]:

            if (tracker.get_intent_of_latest_message() == "authenticate_me") or (tracker.get_slot("user_authenticated")):
                if not tracker.get_slot("user_authenticated"):
                    dispatcher.utter_message(text="Authentication Successful")
                return {"user_authenticated": True}

    async def explain_user_authenticated(self , value: Any, dispatcher: CollectingDispatcher , tracker: Tracker ,
                                             domain: Dict[Text, Any]) -> Dict[Text, Any]:

        dispatcher.utter_message(response="utter_ask_card_status_update_form_user_authenticated")


    async def validate_card_number(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker,
                                             domain: Dict[Text, Any]) -> Dict[Text, Any]:
        text = ""
        slot = None
        if not isinstance(eval(value), int) or (len(value) != 16):
            text = f"Not a Valid Number"
            repeated_validation_counter = tracker.get_slot("repeated_validation_failures")
            if repeated_validation_counter>= MAX_VALIDATION_FAILURES:
                events = await super().explain_requested_slot(domain=domain , tracker=tracker , dispatcher=dispatcher)
                text = ""
            else:
                repeated_validation_counter = repeated_validation_counter + 1
            dispatcher.utter_message(text=text)
            return {"card_number" : slot , "repeated_validation_failures": repeated_validation_counter }

        text = "Looking into it..."
        slot = eval(value)
        dispatcher.utter_message(text= text)
        return {"card_number" : slot , "repeated_validation_failures": 0}


    async def explain_card_number(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        dispatcher.utter_message(text= "Max validation failed. enter card number written at the back of your card")
        return {}


class ValidateBalanceInquiryForm(CustomFormValidationAction):


    def name(self) -> Text:
        """Unique identifier of the form"""
        return "validate_balance_inquiry_form"

    async def validate_user_authenticated(self, value: Any , dispatcher: CollectingDispatcher , tracker: Tracker ,
                                             domain: Dict[Text, Any]) -> Dict[Text, Any]:

            if (tracker.get_intent_of_latest_message() == "authenticate_me") or (tracker.get_slot("user_authenticated")):
                if not tracker.get_slot("user_authenticated"):
                    dispatcher.utter_message(text="Authentication Successful")
                return {"user_authenticated": True}

    async def explain_user_authenticated(self , value: Any, dispatcher: CollectingDispatcher , tracker: Tracker ,
                                             domain: Dict[Text, Any]) -> Dict[Text, Any]:

        dispatcher.utter_message(response="utter_ask_balance_inquiry_form_user_authenticated")


    async def validate_SSN(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker,
                                             domain: Dict[Text, Any]) -> Dict[Text, Any]:
        text = ""
        slot = None
        if not isinstance(eval(value), int) or (len(value) != 4):
            text = f"Not a Valid Information (SSN)"
            repeated_validation_counter = tracker.get_slot("repeated_validation_failures")
            if repeated_validation_counter >= MAX_VALIDATION_FAILURES:
                events = await super().explain_requested_slot(domain=domain, tracker=tracker, dispatcher=dispatcher)
                text = ""
            else:
                repeated_validation_counter = repeated_validation_counter + 1
            dispatcher.utter_message(text=text)
            return {"SSN": slot, "repeated_validation_failures": repeated_validation_counter}

        text = "Looking into it..."
        slot = value
        dispatcher.utter_message(text=text)
        return {"card_number": slot, "repeated_validation_failures": 0}

    async def explain_SSN(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker,
                                  domain: Dict[Text, Any]) -> Dict[Text, Any]:
        dispatcher.utter_message(text="Max validation failed. enter valid SSN")
        return {}

    async def validate_last4ofcard(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker,
                                             domain: Dict[Text, Any]) -> Dict[Text, Any]:
        if value:
            card_number = eval(value)
            return {"last4ofcard": card_number}
        else:
            dispatcher.utter_message(text= "Slot is not set")
            return {"last4ofcard" : None}

class ActionSwitchFormsAsk(Action):
    """Asks to switch forms"""

    def name(self) -> Text:
        return "action_switch_forms_ask"

    async def run(
            self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> List[EventType]:
        """Executes the custom action"""
        active_form_name = tracker.active_loop.get("name")
        intent_name = tracker.latest_message["intent"]["name"]
        next_form_name = NEXT_FORM_NAME.get(intent_name)

        if (active_form_name not in FORM_DESCRIPTION.keys()
                or next_form_name not in FORM_DESCRIPTION.keys()):
            logger.debug(
                f"Cannot create text for `active_form_name={active_form_name}` & "
                f"`next_form_name={next_form_name}`"
            )
            next_form_name = None
        else:
            text = (
                f"We haven't completed the {FORM_DESCRIPTION[active_form_name]} yet. "
                f"Are you sure you want to switch to {FORM_DESCRIPTION[next_form_name]}?"
            )
            buttons = [
                {"payload": "/affirm", "title": "Yes"},
                {"payload": "/deny", "title": "No"},
            ]
            dispatcher.utter_message(text=text, buttons=buttons)


        return [SlotSet("next_form_name", next_form_name)]

class ActionSwitchFormsDeny(Action):
    """Does not switch forms"""

    def name(self) -> Text:
        return "action_switch_forms_deny"

    async def run(
            self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> List[EventType]:
        """Executes the custom action"""
        active_form_name = tracker.active_loop.get("name")

        if active_form_name not in FORM_DESCRIPTION.keys():
            logger.debug(
                f"Cannot create text for `active_form_name={active_form_name}`."
            )
        else:
            text = f"Ok, let's continue with the {FORM_DESCRIPTION[active_form_name]}."
            dispatcher.utter_message(text=text)

        return [SlotSet("next_form_name", None)]

class ActionSwitchFormsAffirm(Action):
    """Switches forms"""

    def name(self) -> Text:
        return "action_switch_forms_affirm"

    async def run(
            self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> List[EventType]:
        """Executes the custom action"""
        active_form_name = tracker.active_loop.get("name")
        next_form_name = tracker.get_slot("next_form_name")

        if (
                active_form_name not in FORM_DESCRIPTION.keys()
                or next_form_name not in FORM_DESCRIPTION.keys()
        ):
            logger.debug(
                f"Cannot create text for `active_form_name={active_form_name}` & "
                f"`next_form_name={next_form_name}`"
            )
        else:
            text = (
                f"Great. Let's switch from the {FORM_DESCRIPTION[active_form_name]} "
                f"to {FORM_DESCRIPTION[next_form_name]}. "
                f"Once completed, you will have the option to switch back."
            )
            dispatcher.utter_message(text=text)

        return [
            SlotSet("previous_form_name", active_form_name),
            SlotSet("next_form_name", None),
        ]

class ActionSwitchBackAsk(Action):
    """Asks to switch back to previous form"""

    def name(self) -> Text:
        return "action_switch_back_ask"

    async def run(
            self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict
    ) -> List[EventType]:
        """Executes the custom action"""
        previous_form_name = tracker.get_slot("previous_form_name")

        if previous_form_name not in FORM_DESCRIPTION.keys():
            logger.debug(
                f"Cannot create text for `previous_form_name={previous_form_name}`"
            )
            previous_form_name = None
        else:
            text = (
                f"Would you like to go back to the "
                f"{FORM_DESCRIPTION[previous_form_name]} now?."
            )
            buttons = [
                {"payload": "/affirm", "title": "Yes"},
                {"payload": "/deny", "title": "No"},
            ]
            dispatcher.utter_message(text=text, buttons=buttons)

        return [SlotSet("previous_form_name", None)]

    # async def validate_Person(self, value: Text, dispatcher: CollectingDispatcher, tracker: Tracker,
    #                                          domain: Dict[Text, Any]) -> Dict[Text, Any]:
    #
    #     if isinstance(value , str):
    #         return {"Person" : value}
    #     else:
    #         dispatcher.utter_message(text = "Enter Valid Name")
    #         return {"Person": None}
    #
    # async def explain_Person(self, value: Any, dispatcher: CollectingDispatcher, tracker: Tracker,
    #                                         domain: Dict[Text, Any]) -> Dict[Text, Any]:
    #     dispatcher.utter_message(response= "utter_ask_balance_inquiry_form_Person")





# class ActionUpdateCardStatus(Action):
#
#     def name(self) -> Text:
#         return "action_update_card_status"
#
#     def run(self, dispatcher: CollectingDispatcher,
#             tracker: Tracker,
#             domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
#
        # is_auth = tracker.get_slot("is_user_authenticated")
        # if is_auth:
        #     card_number = eval(tracker.get_slot("card_number"))
        #     if card_number:
        #         card_present = len(cards[cards['Cards'] == card_number]['Status'])
        #         if card_present:
        #             status = cards[cards['Cards'] == card_number]['Status'].values[0]
        #             if status == 'Activated':
        #                 cards.loc[cards['Cards'] == card_number , 'Status'] = 'Blocked'
        #                 cards.to_excel(cards_db_file_name, index = False)
        #                 dispatcher.utter_message(text="Your cards hab been temporarily blocked")
        #             else:
        #                 dispatcher.utter_message(text= "Your cards is already blocked" )
        #         else:
        #             dispatcher.utter_message(text="No record found against this Card number")
        # else:
        #     dispatcher.utter_message(response = "utter_need_login_first")
        #
        # return []


# class ActionAuthenticateUser(Action):
#
#     def name(self) -> Text:
#         return "action_authenticate_user"
#
#     def run(self, dispatcher: CollectingDispatcher,
#             tracker: Tracker,
#             domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
#         if tracker.get_intent_of_latest_message() == "authenticate_me":
#             dispatcher.utter_message(text="Authentication Successful")
#         return [SlotSet("is_user_authenticated", True)]
