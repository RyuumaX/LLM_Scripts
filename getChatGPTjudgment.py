import argparse
import copy
import json
from datetime import date

import openai
from tenacity import (retry, stop_after_attempt, wait_random_exponential)

SYSTEM_PROMPT = ("Hinter dem Text 'Kundenmail:' findest du die Anfrage eines Kunden an einen Kundenbetreuer. "
                 "Hinter dem Text 'Antwort des Kundenbetreuers:' steht die Antwort auf die Kundenanfrage."
                 "Bewerte, ob die Antwort des Kundenbetreuers nachvollziehbar ist, oder nicht. "
                 "Bewerte die Antwort mit 'Gut', oder 'Schlecht'."
                 "Schreibe außer der Bewertung nichts."
                 "Bewerte unfreundliche oder leere Antworten mit 'Schlecht'."
                 "Bewerte Antworten die grammatikalische Fehler enthalten mit 'Schlecht'."
                 "Bewerte Antworten die ganz oder teilweise in Englisch verfasst sind mit 'Schlecht'.")

def get_currentPrompt(index):
    messages = [{"role": "system",
                 "content": f"{SYSTEM_PROMPT}"},
                {"role": "user", "content": f"Kundenmail: {parsed_json['entries'][index]['request']['body']}"},
                {"role": "user", "content": f"Antwort: {parsed_json['entries'][index]['response']['body']}"}]
    return messages


@retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
def completion_with_backoff(**kwargs):
    return openai.ChatCompletion.create(**kwargs)


if __name__ == '__main__':

    # define commandline arguments
    cl_argparser = argparse.ArgumentParser(
        description="Takes a JSON File with emails, LLM Responses to those emails and sends it to an OpenAI model. That model then judges the answers on quality.")
    cl_argparser.add_argument("-f", "--file", help="The path to the input json file.")
    cl_argparser.add_argument("-o", "--output",
                              help="Path of the folder to put the output JSON-file in. Defaults to current working dir. Filename defaults to {modelname}_responses.json")
    cl_argparser.add_argument("-m", "--model", help="Model to use for entry",
                              choices=["text-davinci-003", "gpt-3.5-turbo"], default="gpt-3.5-turbo")
    cl_argparser.add_argument("-c", "--count", type=int, help="Number of entries to process from file")
    cl_argparser.add_argument("--start", help="first entry to process from file", default=1, type=int)
    cl_argparser.add_argument("-k", "--key", help="API-Key to use")

    # ...and parse
    args = cl_argparser.parse_args()
    file_path = args.file
    modelname = args.model
    openai.api_key = args.key

    dict_template = {"rating": {"from": "", "date": "", "value": ""}}

    # read in the local LLM's answers
    parsed_json = None
    if not file_path:
        file_path = './example_data/output.json'

    with open(file_path) as user_file:
        parsed_json = json.load(user_file)

    num_entries = args.count if args.count else len(parsed_json['entries'])
    start = args.start - 1 if args.start else 0
    end = (start + num_entries) if (start + num_entries) < len(parsed_json['entries']) else len(parsed_json['entries'])
    # print the processing parameters
    print(f"using model: {modelname}")
    print(f"first entry pos: {args.start}")
    print(f"last entry pos: {end}")

    for index, entry in enumerate(list(range(start, end, 1))):
        print(f"processing entry number {index} of {num_entries}, pos: {entry + 1}")
        prompt = get_currentPrompt(entry)
        # if there is an empty answer just set the rating to bad, no api call needed
        if parsed_json['entries'][entry]['response']['body'] == "":
            dict_template['rating']['value'] = "Schlecht"
        else:
            # max_tokens gives the maximum number of tokens generated by the model as the response; temperature determines
            # how "creative" the model is. Lower values make the answer more deterministic.
            completion = completion_with_backoff(model=modelname, messages=prompt, max_tokens=16, temperature=0)
            dict_template['rating']['value'] = completion.choices[0]['message']['content']
        dict_template['rating']['from'] = modelname
        dict_template['rating']['date'] = str(date.today())
        parsed_json['entries'][entry].update(copy.deepcopy(dict_template))
    parsed_json['header']['ratingSysPrompt'] = SYSTEM_PROMPT

    #write out ratings to file
    if not args.output:
        out_path = f"./{parsed_json['header']['model']}_responses_rated_by_{modelname}.json"
    else:
        out_path = args.output.strip("/")
        out_path = f"/{out_path}/{parsed_json['header']['model']}_responses_rated_by_{modelname}.json"

    with open(out_path, "w", encoding="utf-8") as write_file:
        json.dump(parsed_json, write_file, indent=4, ensure_ascii=False)
