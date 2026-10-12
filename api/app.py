from flask import Flask, render_template, request, jsonify, Response
from urllib.parse import quote, urlparse, unquote
import json
import os
import sys
import subprocess
import tempfile

app = Flask(__name__, template_folder='../templates')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROVIDERS_PATH = os.path.join(PROJECT_DIR, 'providers.json')


def get_template_list():
    template_dir = os.path.join(PROJECT_DIR, 'config_template')
    return sorted(os.path.splitext(name)[0] for name in os.listdir(template_dir)
                  if name.endswith('.json'))


@app.after_request
def prevent_caching(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/')
def index():
    with open(PROVIDERS_PATH, 'r', encoding='utf-8') as file:
        default_providers = json.load(file)
    template_options = [f"{index + 1}、{template}"
                        for index, template in enumerate(get_template_list())]
    return render_template(
        'index.html', template_options=template_options,
        temp_json_data=json.dumps(default_providers, indent=4, ensure_ascii=False)
    )


def generate_response(providers, template_index='0', gh_proxy_index=''):
    if not isinstance(providers, dict) or not isinstance(providers.get('subscribes'), list):
        return jsonify(status='error', message='配置必须是包含 subscribes 数组的 JSON 对象。'), 400
    try:
        template_index = int(template_index)
    except (TypeError, ValueError):
        return jsonify(status='error', message='模板编号无效。'), 400
    if not providers.get('config_template') and not 0 <= template_index < len(get_template_list()):
        return jsonify(status='error', message='模板编号无效。'), 400

    # Each request owns its provider data, output file and subprocess.
    providers = dict(providers)
    try:
        with tempfile.TemporaryDirectory(prefix='sing-box-subscribe-') as temp_dir:
            output_path = os.path.join(temp_dir, 'config.json')
            providers['save_config_path'] = output_path
            providers['auto_backup'] = False
            encoded_providers = json.dumps(
                json.dumps(providers, ensure_ascii=False), ensure_ascii=False
            )
            subprocess.run(
                [sys.executable, os.path.join(PROJECT_DIR, 'main.py'),
                 '--template_index', str(template_index),
                 '--temp_json_data', encoded_providers,
                 '--gh_proxy_index', str(gh_proxy_index)],
                cwd=PROJECT_DIR, check=True, timeout=60,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            with open(output_path, 'r', encoding='utf-8') as file:
                content = file.read()
            json.loads(content)
        return Response(content, content_type='text/plain; charset=utf-8')
    except subprocess.TimeoutExpired:
        return jsonify(status='error', message='配置生成超时，请检查订阅。'), 504
    except (subprocess.CalledProcessError, OSError, ValueError):
        return jsonify(status='error', message='配置生成失败，请检查订阅和模板。'), 500


@app.route('/config/<path:url>', methods=['GET'])
def config(url):
    user_agent = request.headers.get('User-Agent') or ""
    rua_values = os.getenv('RUA')
    if rua_values and any(rua_value in user_agent for rua_value in rua_values.split(',')):
        return Response(json.dumps({'status': 'error', 'message': 'block'}, indent=4, ensure_ascii=False),
                        content_type='application/json; charset=utf-8', status=403)
    substrings = os.getenv('STR')
    if substrings and any(substring in url for substring in substrings.split(',')):
        return Response(json.dumps({'status': 'error', 'message_CN': '填写参数不符合规范'}, indent=4, ensure_ascii=False),
                        content_type='application/json; charset=utf-8', status=403)
    temp_json_data = json.loads('{"subscribes":[{"url":"URL","tag":"tag_1","enabled":true,"emoji":1,"subgroup":"","prefix":"","ex-node-name": "","User-Agent":"clash.meta"},{"url":"URL","tag":"tag_2","enabled":false,"emoji":1,"subgroup":"","prefix":"","ex-node-name": "","User-Agent":"clash.meta"},{"url":"URL","tag":"tag_3","enabled":false,"emoji":1,"subgroup":"","prefix":"","ex-node-name": "","User-Agent":"clash.meta"}],"auto_set_outbounds_dns":{"proxy":"","direct":""},"save_config_path":"./config.json","auto_backup":false,"exclude_protocol":"ssr","config_template":"","Only-nodes":false}')
    subscribe = temp_json_data['subscribes'][0]
    subscribe2 = temp_json_data['subscribes'][1]
    subscribe3 = temp_json_data['subscribes'][2]
    query_string = request.query_string.decode('utf-8')
    #encoded_url = quote(url, safe=':/')  # 对 url 进行编码
    encoded_url = unquote(url)
    index_of_colon = encoded_url.find(":")

    if not query_string:
        if any(substring in encoded_url for substring in ['&emoji=', '&file=', '&eps=', '&enn=']):
            if '|' in encoded_url:
                param = urlparse(encoded_url.rsplit('&', 1)[-1])
            else:
                param = urlparse(encoded_url.split('&', 1)[-1])
            request.args = dict(item.split('=') for item in param.path.split('&'))
            if request.args.get('prefix'):
                request.args['prefix'] = unquote(request.args['prefix'])
            if request.args.get('eps'):
                request.args['eps'] = unquote(request.args['eps'])
            if request.args.get('enn'):
                request.args['enn'] = unquote(request.args['enn'])
            if request.args.get('file'):
                index = request.args.get('file').find(":")
                next_index = index + 2
                if index != -1:
                    if next_index < len(request.args['file']) and request.args['file'][next_index] != "/":
                        request.args['file'] = request.args['file'][:next_index-1] + "/" + request.args['file'][next_index-1:]
    else:
        if any(substring in query_string for substring in ['&emoji=', '&file=', '&eps=', '&enn=']):
            param = urlparse(query_string.split('&', 1)[-1])
            request.args = dict(item.split('=') for item in param.path.split('&'))
            if request.args.get('prefix'):
                request.args['prefix'] = unquote(request.args['prefix'])
            if request.args.get('eps'):
                request.args['eps'] = unquote(request.args['eps'])
            if request.args.get('enn'):
                request.args['enn'] = unquote(request.args['enn'])
            if request.args.get('file'):
                index = request.args.get('file').find(":")
                next_index = index + 2
                if index != -1:
                    if next_index < len(request.args['file']) and request.args['file'][next_index] != "/":
                        request.args['file'] = request.args['file'][:next_index-1] + "/" + request.args['file'][next_index-1:]
            elif 'file=' in query_string:
                index = query_string.find("file=")
                request.args['file'] = query_string.split('file=')[-1].split('&', 1)[0]

    if index_of_colon != -1:
        # 检查 ":" 后面是否只有一个 "/"，如果是，添加一个额外的 "/"
        next_char_index = index_of_colon + 2
        if next_char_index < len(encoded_url) and encoded_url[next_char_index] != "/":
            encoded_url = encoded_url[:next_char_index-1] + "/" + encoded_url[next_char_index-1:]
    if query_string:
        full_url = f"{encoded_url}?{query_string}"
    else:
        if any(substring in encoded_url for substring in ['&emoji=', '&file=']):
            full_url = f"{encoded_url.split('&')[0]}"
        else:
            full_url = f"{encoded_url}"


    emoji_param = request.args.get('emoji', '')
    file_param = request.args.get('file', '')
    tag_param = request.args.get('tag', '')
    ua_param = request.args.get('ua', '')
    UA_param = request.args.get('UA', '')
    pre_param = request.args.get('prefix', '')
    eps_param = request.args.get('eps', '')
    enn_param = request.args.get('enn', '')
    gh_proxy_param = request.args.get('gh', '')

    # 构建要删除的字符串列表
    params_to_remove = [
        f'&prefix={quote(pre_param)}',
        f'&ua={ua_param}',
        f'&UA={UA_param}',
        f'&file={file_param}',
        f'file={file_param}',
        f'&emoji={emoji_param}',
        f'&tag={tag_param}',
        f'&gh={gh_proxy_param}',
        f'&eps={quote(eps_param)}',
        f'&enn={quote(enn_param)}'
    ]
    # 从url中删除这些字符串
    full_url = full_url.replace(',', '%2C')
    for param in params_to_remove:
        if param in full_url:
            full_url = full_url.replace(param, '')
    if request.args.get('url'):
        full_url = full_url
    else:
        full_url = unquote(full_url)
    if '/api/v4/projects/' in full_url:
        parts = full_url.split('/api/v4/projects/')
        full_url = parts[0] + '/api/v4/projects/' + parts[1].replace('/', '%2F', 1)
    url_parts = full_url.split('|')
    if len(url_parts) > 1:
        subscribe['url'] = full_url.split('url=', 1)[-1].split('|')[0] if full_url.startswith('url') else full_url.split('|')[0]
        subscribe['ex-node-name'] = enn_param
        subscribe2['url'] = full_url.split('url=', 1)[-1].split('|')[1] if full_url.startswith('url') else full_url.split('|')[1]
        subscribe2['emoji'] = 1
        subscribe2['enabled'] = True
        subscribe2['subgroup'] = ''
        subscribe2['prefix'] = ''
        subscribe2['ex-node-name'] = enn_param
        subscribe2['User-Agent'] = 'clash.meta'
        if len(url_parts) == 3:
            subscribe3['url'] = full_url.split('url=', 1)[-1].split('|')[2] if full_url.startswith('url') else full_url.split('|')[2]
            subscribe3['enabled'] = True
            subscribe3['ex-node-name'] = enn_param
    if len(url_parts) == 1:
        subscribe['url'] = full_url.split('url=', 1)[-1] if full_url.startswith('url') else full_url
        subscribe['emoji'] = int(emoji_param) if emoji_param.isdigit() else subscribe.get('emoji', '')
        subscribe['tag'] = tag_param if tag_param else subscribe.get('tag', '')
        subscribe['prefix'] = pre_param if pre_param else subscribe.get('prefix', '')
        subscribe['ex-node-name'] = enn_param
        subscribe['User-Agent'] = ua_param if ua_param else 'clash.meta'
    temp_json_data['exclude_protocol'] = eps_param if eps_param else temp_json_data.get('exclude_protocol', '')
    temp_json_data['config_template'] = unquote(file_param) if file_param else temp_json_data.get('config_template', '')
    #page_content = f"生成的页面内容：{full_url}"
    #return page_content
    selected_template_index = '0'
    selected_gh_proxy_index = ''
    if file_param.isdigit():
        temp_json_data['config_template'] = ''
        selected_template_index = str(int(file_param) - 1)
    if gh_proxy_param.isdigit():
        selected_gh_proxy_index = str(int(gh_proxy_param) - 1)
    return generate_response(temp_json_data, selected_template_index, selected_gh_proxy_index)


@app.route('/generate_config', methods=['POST'])
def generate_config():
    try:
        providers = json.loads(request.form.get('temp_json_data', ''))
    except (TypeError, ValueError):
        return jsonify(status='error', message='请填写有效的 provider JSON。'), 400
    return generate_response(providers, request.form.get('template_index', '0'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
