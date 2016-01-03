import gevent.monkey; gevent.monkey.patch_all()
import gevent
from flask import Flask, jsonify, request, render_template, session, url_for, redirect
from urllib import urlencode
import json
import requests
import ga4gh
import config
import snps

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
GENOTYPES = {snp: snp_data['Code'] for snp, snp_data in snps.DATA.iteritems()} 


def get_access_token(auth_code):
    '''
    exchange `code` with `access token`
    '''
    exchange_data = {
        'code': auth_code,
        'redirect_uri': config.REDIRECT_URI,
        'client_id': config.CLIENT_ID,
        'grant_type': 'authorization_code'
    }
    resp = requests.post(config.AUTH_BASE+'/token', data=exchange_data)
    return resp.json()


def upload_seq(seq, access_token): 
    resp = requests.post('%s/Sequence?_format=json'% config.API_BASE,
            data=json.dumps(seq), 
            headers={'Authorization': 'Bearer %s'% access_token})


@app.route('/load')
def load(): # load appropriate data from GA4GH
    callset_id = sample_id = session['sample_id']
    variants, variantset_ids = ga4gh.search_variants(
            GENOTYPES,
            ga4gh.OKG,
            callSetIds=[sample_id],
            repo_id='google')
    pid = session['patient'] 
    uploads = []
    for rsid, variant in variants:
        coord = snps.COORDINATES[rsid]
        interp = 'positive' if float(snps.DATA[rsid]['Risk']) > 1 else 'negative'
        seq = {
            'resourceType': 'Sequence',
            'type': DNA,
            'coordinate': [
                   {"start": coord['pos']-1,
                   "end": coord['pos'], 
                   "chromosome": {'text': coord['chromosome']},
                   "genomeBuild": {'text': 'GRCh37'},
                   }],
            'variation': {'text': rsid},
            'species': {'text': 'Homo sapiens'},
            "repository": [
                   {
                   "url": "https://www.googleapis.com/genomics/v1beta2",
                   "variantId": variantset_ids
                   }
                   ]
        }
        uploads.append(gevent.spawn(upload_seq, seq, session['access_token']))
    for g in uploads:
        g.join()
    return redirect('%s/Sequence' % config.API_BASE)


@app.route('/recv-redirect')
def recv_redirect():
    credentials = get_access_token(request.args['code'])
    session.update(credentials) 
    return redirect(url_for('load')) 


@app.route('/prompt-select-sample')
def prompt_select_sample():
    return render_template('select.html')


@app.route('/fhir-app/launch.html')
def launch():
    if 'selected' not in request.args:
        session['launch_args'] = json.dumps(request.args)
        return redirect(url_for('prompt_select_sample'))

    redirect_args = {
        'scope': ' '.join(config.SCOPES+['launch:'+request.args['launch']]),
        'client_id': config.CLIENT_ID,
        'redirect_uri': config.REDIRECT_URI,
        'response_type': 'code'}
    return redirect('%s/authorize?%s'% (config.AUTH_BASE, urlencode(redirect_args)))


@app.route('/select-sample')
def select_sample():
    launch_args = json.loads(session['launch_args'])
    launch_args['selected'] = ''
    session['sample_id'] = request.args['sample_id']
    return redirect('%s?%s'% (
        url_for('launch'),
        urlencode(launch_args)))


@app.route('/callsets')
def get_callsets(): 
    vset_search = ga4gh.search('variantsets', datasetIds=[ga4gh.OKG], repo_id='google') 
    vset_id = vset_search['variantSets'][0]['id']
    callset_search = ga4gh.search(
            'callsets',
            variantSetIds=[vset_id],
            repo_id='google',
            pageSize=10,
            **request.args)
    return jsonify(callset_search)


if __name__ == '__main__':
    app.run(debug=True, port=8000)
