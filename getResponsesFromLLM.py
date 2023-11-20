import argparse
import copy
import hashlib
import json
import os
import time
from datetime import date, datetime
from openai import OpenAI
from tenacity import (retry, stop_after_attempt, wait_random_exponential)

SYSTEM_PROMPT = f"""Du bist ein Kundenbetreuer bei einem deutschen Energieversorger.
Unten steht eine Mail eines Kunden.
Formuliere eine freundliche Antwortmail und gib diese aus.
Sprich den Kunden stets mit Sie an."""


def get_currentPrompt(index):
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Kundenmail: {parsed_json[index]['requestMail']}".strip()}, ]
    return messages


@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
def completion_with_backoff(**kwargs):
    return client.chat.completions.create(**kwargs)


def get_currentDatetime():
    # %H für Stunde, %M für Minuten
    now = datetime.now()
    dt_string = now.strftime("%Y-%m-%d")
    return dt_string


if __name__ == '__main__':

    # Kommandozeilenparameter parsen
    cl_argparser = argparse.ArgumentParser(
        description="Takes a JSON File with emails and sends it to an OpenAI API compatible server for LLM processing."
                    "LLM-Responses are saved to JSON.")
    cl_argparser.add_argument("-f", "--file", help="The path to the input json file.")
    cl_argparser.add_argument("-o", "--output", help="Path of the folder to put the output JSON-file in."
                                                     "Defaults to current working dir. Filename defaults to {modelname}_responses.json")
    cl_argparser.add_argument("-m", "--model", help="Name of the LLM-model to use.", default="Llama-2-13b-chat-hf")
    cl_argparser.add_argument("-c", "--count", type=int, help="Number of Entries to read from the input file. "
                                                              "If not supplied, the entire content of the file is used.")
    cl_argparser.add_argument("-s", "--server", help="Address of the Server that hosts the LLM")

    args = cl_argparser.parse_args()
    file_path = args.file
    entry_count = args.count

    if 'OPENAI_API_BASE' in os.environ:
        pass
    else:
        os.environ['OPENAI_API_BASE'] = f"http://{args.server}/v1"
        print(os.environ['OPENAI_API_BASE'])

    if 'OPENAI_API_KEY' in os.environ:
        pass
    else:
        os.environ['OPENAI_API_KEY'] = "EMPTY"

    client = OpenAI(base_url="http://172.17.0.1:8082/v1")

    # Mails aus JSON-Datei einlesen
    parsed_json = None
    if not file_path:
        file_path = './example_data/output.json'

    with open(file_path) as user_file:
        parsed_json = json.load(user_file)

    # Template Dictionary
    json_template = {"header": {"model": "", "hyperparams": {}, "systemPrompt": SYSTEM_PROMPT, "date": ""},
                     "entries": []}

    entry_template = {"id": "", "request": {"body": "", "subject": "", "tags": {}},
                      "response": {"body": "", "tags": {}}}

    hyperparams = {"temperature": 0, "max_tokens": 512}

    print("JSON-file used: " + file_path)
    print("Output-file saved to Path: " + args.output)

    modelnames = [args.model]

    for modelname in modelnames:
        print(modelname)
        json_template['header']['model'] = f"{modelname}"
        json_template['header']['date'] = get_currentDatetime()
        json_template['header']['hyperparams'].update(hyperparams)

        for mailIndex in range(entry_count):
            # doppelte newlines entfernen um Token zu sparen
            parsed_json[mailIndex]['requestMail'] = (parsed_json[mailIndex]['requestMail'].replace('\n\n', '\n'))
            # Hash der Kundenmail (!= prompt) als ID verwenden
            msg_hash = hashlib.sha1(parsed_json[mailIndex]['requestMail'].encode("utf-8"))
            entry_template['id'] = msg_hash.hexdigest()
            prompt = get_currentPrompt(mailIndex)  # aktuellen prompt aus Nutzermail bauen
            # create a completion and measure time
            start_measure = time.time()
            completion = completion_with_backoff(model=modelname, messages=prompt, max_tokens=hyperparams['max_tokens'],
                                                 temperature=hyperparams['temperature'])
            end_measure = time.time()
            elapsed_time = end_measure - start_measure

            print("working on entry " + str(mailIndex + 1) + " with ID " + entry_template['id'] + " took: " + str(
                round(elapsed_time, 2)) + " seconds")
            entry_template['request']['body'] = parsed_json[mailIndex]['requestMail']
            entry_template['request']['subject'] = parsed_json[mailIndex]['process']
            entry_template['response']['body'] = completion.choices[0].message.content.replace('\n\n', '\n')
            json_template['entries'].append(copy.deepcopy(entry_template))

        if not args.output:
            out_path = f"./{modelname}_responses.json"
        else:
            out_path = args.output.strip("/")
            out_path = f"/{out_path}/{modelname}_responses.json"

        with open(out_path, 'w', encoding='utf-8') as write_file:
            json.dump(json_template, write_file, indent=4, ensure_ascii=False)
