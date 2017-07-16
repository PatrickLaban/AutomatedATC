import boto3
from boto3.dynamodb.conditions import Key, Attr


# --------------- Helpers that build all of the responses ----------------------

def build_speechlet_response(title, output, reprompt_text, should_end_session):
    return {
        'outputSpeech': {
            'type': 'PlainText',
            'text': output
        },
        'card': {
            'type': 'Simple',
            'title': "SessionSpeechlet - " + title,
            'content': "SessionSpeechlet - " + output
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': reprompt_text
            }
        },
        'shouldEndSession': should_end_session
    }


def build_response(session_attributes, speechlet_response):
    return {
        'version': '1.0',
        'sessionAttributes': session_attributes,
        'response': speechlet_response
    }


# --------------- Functions that control the skill's behavior ------------------

def get_welcome_response():
    """ If we wanted to initialize the session to have some attributes we could
    add those here
    """

    session_attributes = {"current_aircraft": None}
    card_title = "Welcome"
    speech_output = "ATC active. "
    # If the user either does not reply to the welcome message or says something
    # that is not understood, they will be prompted again with this text.
    reprompt_text = "Please make a request."
    should_end_session = False
    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, reprompt_text, should_end_session))


def handle_session_end_request():
    card_title = "Session Ended"
    speech_output = "Thank you for trying the Alexa Skills Kit sample. " \
                    "Have a nice day! "
    # Setting this to true ends the session and exits the skill.
    should_end_session = True
    return build_response({}, build_speechlet_response(
        card_title, speech_output, None, should_end_session))


class Aircraft:
    def __init__(self, call_sign, make, position=None):
        self.call_sign = call_sign
        self.make = make
        self.position = position

    def set_position(self, position):
        self.position = position

    def serialize_for_dynamodb(self):
        return {"CallSign": self.call_sign, "make": self.make, "pattern_position": self.position}


def get_aircraft_by_call_sign(intent):
    if 'Callsign' in intent['slots'] and 'Make' in intent['slots']:
        ddb = boto3.resource('dynamodb').Table('Aircraft')
        call_sign = intent['slots']['Callsign']['value']
        make = intent['slots']['Make']['value']

        response = ddb.query(
            KeyConditionExpression=Key('CallSign').eq(call_sign)
        )

        if response['Items']:
            r_aircraft = response['Items'][0]
            current_aircraft = Aircraft(r_aircraft['CallSign'], r_aircraft['make'], r_aircraft['pattern_position'])
        else:
            current_aircraft = Aircraft(call_sign, make)
            ddb.put_item(Item=current_aircraft.serialize_for_dynamodb())
        return current_aircraft


def update_position(intent, session):
    """ Sets the position in the session and prepares the speech to reply to the
    user.
    """

    card_title = intent['name']
    should_end_session = False

    if 'Position' in intent['slots']:
        current_aircraft = get_aircraft_by_call_sign(intent)
        current_aircraft.position = intent['slots']['Position']['value']

        ddb = boto3.resource('dynamodb').Table('Aircraft')

        response = ddb.update_item(
            Key={'CallSign': current_aircraft.call_sign},
            UpdateExpression="set pattern_position = :p",
            ExpressionAttributeValues={
                ':p': current_aircraft.position
            },
            ReturnValues="UPDATED_NEW"
        )

        speech_output = "You are currently in the pattern at " + \
                        current_aircraft.position + ". "
        reprompt_text = "You can ask me about other traffic by saying, " \
                        "what aircraft are in the area?"
    else:
        speech_output = "I did not copy your position. " \
                        "Please say again."
        reprompt_text = "I did not copy your position. " \
                        "You can tell me your position in the pattern by saying, " \
                        "my position is downwind."
    session_attributes = {}
    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, reprompt_text, should_end_session))


def get_traffic(intent, session):
    session_attributes = {}
    reprompt_text = None

    ddb = boto3.resource('dynamodb').Table('Aircraft')

    response = ddb.scan()

    if response['Items']:
        speech_output = ""
        for aircraft in response['Items']:
            if aircraft['pattern_position'] is not None:
                current_aircraft = Aircraft(aircraft['CallSign'], aircraft['make'], aircraft['pattern_position'])
                speech_output += current_aircraft.make + current_aircraft.call_sign + \
                                 "is in the pattern at " + current_aircraft.position + ".. "
            else:
                current_aircraft = Aircraft(aircraft['CallSign'], aircraft['make'], aircraft['pattern_position'])
                speech_output += current_aircraft.make + current_aircraft.call_sign + \
                                 "is in the area.. "
    else:
        speech_output = "There are no other aircraft in the pattern."
    should_end_session = False

    return build_response(session_attributes, build_speechlet_response(
        intent['name'], speech_output, reprompt_text, should_end_session))


def check_clearance(pattern_request):
    clearance_dict = {"runway": {"final", "landing", "base", "runway"},
                      "final": {"landing", "base", "runway", "final"},
                      "landing": {"runway", "take-off", "landing"},
                      "take-off": {"crosswind", "take-off"},
                      "downwind": {"base", "downwind"},
                      "base": {"final", "landing", "runway", "take-off", "base"},
                      }
    negative_clearance_list = clearance_dict[pattern_request]
    ddb = boto3.resource('dynamodb').Table('Aircraft')
    current_traffic = ddb.scan()
    if current_traffic['Items']:
        for aircraft in current_traffic['Items']:
            if aircraft['pattern_position'] in negative_clearance_list:
                return False
    return True


def get_clearance(intent, session):
    session_attributes = {}
    reprompt_text = None

    current_aircraft = get_aircraft_by_call_sign(intent)
    pattern_request = intent['slots']['Position']['value']
    if check_clearance(pattern_request):
        speech_output = current_aircraft.make + " " + current_aircraft.call_sign + \
            pattern_request + " clearance granted. "
    else:
        speech_output = current_aircraft.make + " " + current_aircraft.call_sign + \
                        "  " + pattern_request + " clearance denied. "

    should_end_session = False

    return build_response(session_attributes, build_speechlet_response(
        intent['name'], speech_output, reprompt_text, should_end_session))


# --------------- Events ------------------

def on_session_started(session_started_request, session):
    """ Called when the session starts """

    print("on_session_started requestId=" + session_started_request['requestId']
          + ", sessionId=" + session['sessionId'])


def on_launch(launch_request, session):
    """ Called when the user launches the skill without specifying what they
    want
    """

    print("on_launch requestId=" + launch_request['requestId'] +
          ", sessionId=" + session['sessionId'])
    # Dispatch to your skill's launch
    return get_welcome_response()


def on_intent(intent_request, session):
    """ Called when the user specifies an intent for this skill """

    print("on_intent requestId=" + intent_request['requestId'] +
          ", sessionId=" + session['sessionId'])

    intent = intent_request['intent']
    intent_name = intent_request['intent']['name']

    # Dispatch to your skill's intent handlers
    if intent_name == "UpdatePositionIntent":
        return update_position(intent, session)
    elif intent_name == "TrafficIntent":
        return get_traffic(intent, session)
    elif intent_name == "ClearanceIntent":
        return get_clearance(intent, session)
    elif intent_name == "AMAZON.HelpIntent":
        return get_welcome_response()
    elif intent_name == "AMAZON.CancelIntent" or intent_name == "AMAZON.StopIntent":
        return handle_session_end_request()
    else:
        raise ValueError("Invalid intent")


def on_session_ended(session_ended_request, session):
    """ Called when the user ends the session.

    Is not called when the skill returns should_end_session=true
    """
    print("on_session_ended requestId=" + session_ended_request['requestId'] +
          ", sessionId=" + session['sessionId'])
    # add cleanup logic here


# --------------- Main handler ------------------

def lambda_handler(event, context):
    """ Route the incoming request based on type (LaunchRequest, IntentRequest,
    etc.) The JSON body of the request is provided in the event parameter.
    """
    print("event.session.application.applicationId=" +
          event['session']['application']['applicationId'])

    """
    Uncomment this if statement and populate with your skill's application ID to
    prevent someone else from configuring a skill that sends requests to this
    function.
    """
    # if (event['session']['application']['applicationId'] !=
    #         "amzn1.echo-sdk-ams.app.[unique-value-here]"):
    #     raise ValueError("Invalid Application ID")

    if event['session']['new']:
        on_session_started({'requestId': event['request']['requestId']},
                           event['session'])
    if event['request']['type'] == "LaunchRequest":
        return on_launch(event['request'], event['session'])
    elif event['request']['type'] == "IntentRequest":
        return on_intent(event['request'], event['session'])
    elif event['request']['type'] == "SessionEndedRequest":
        return on_session_ended(event['request'], event['session'])
