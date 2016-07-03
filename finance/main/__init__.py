from flask import Blueprint, jsonify, render_template, request
from logbook import Logger

from finance.models import Account, Asset, Portfolio
from finance.utils import date_range

main_module = Blueprint('main', __name__, template_folder='templates')
log = Logger()


ENTITY_MAPPINGS = {
    'account': {
        'class': Account,
        'view_template': 'view_account.html',
    },
    'asset': {
        'class': Asset,
    },
    'portfolio': {
        'class': Portfolio,
        'view_template': 'view_portfolio.html',
    }
}


def get_entity_class(entity_type):
    try:
        return ENTITY_MAPPINGS[entity_type]['class']
    except KeyError:
        from finance.models import db
        return db.Model


def get_view_template(entity_type):
    try:
        return ENTITY_MAPPINGS[entity_type]['view_template']
    except KeyError:
        return 'view_entity.html'


@main_module.route('/')
def index():
    portfolio = Portfolio.query.first()
    start, end = map(request.args.get, ['start', 'end'])
    context = {
        'portfolio': portfolio,
        'start': start,
        'end': end,
    }
    return render_template('index.html', **context)


# FIXME: deprecated
@main_module.route('/data')
def data():
    portfolio = Portfolio.query.first()
    start, end = map(request.args.get, ['start', 'end'])
    def gen(start, end):
        for date in date_range(start, end):
            log.info('Calculating net worth on {}', date)
            nw = portfolio.net_worth(date)
            v = float(nw)
            yield date.strftime('%Y%m%d'), v, v, v, v, 0

    return jsonify({'data': [x for x in gen(start, end)]})


@main_module.route('/portfolios/<int:portfolio_id>/nav')
def nav(portfolio_id):
    """Returns the net asset values (NAVs) for a given period of time."""
    portfolio = Portfolio.query.get(portfolio_id)
    start, end = map(request.args.get, ['start', 'end'])

    portfolio.daily_net_worth(start, end)

    return ''


@main_module.route('/entities/<entity_type>')
def list_entities(entity_type):
    entity_class = get_entity_class(entity_type)
    entities = entity_class.query.all()
    context = {
        'entities': entities,
    }
    return render_template('list_entities.html', **context)


@main_module.route('/entities/<entity_type>:<int:entity_id>')
def view_entity(entity_type, entity_id):
    entity_class = get_entity_class(entity_type)
    view_template = get_view_template(entity_type)
    entity = entity_class.query.get(entity_id)
    context = {
        'entity': entity,
        'entity_class': entity_class,
    }
    return render_template(view_template, **context)
