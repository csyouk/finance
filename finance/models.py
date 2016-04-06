from datetime import datetime

from flask.ext.login import UserMixin
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSON
import uuid64

from finance.exceptions import (
    AssetValueUnavailableException, InvalidTargetAssetException)


db = SQLAlchemy()
JsonType = db.String().with_variant(JSON(), 'postgresql')


class CRUDMixin(object):
    """Copied from https://realpython.com/blog/python/python-web-applications-with-flask-part-ii/
    """  # noqa

    __table_args__ = {'extend_existing': True}

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=False,
                   default=uuid64.issue())

    @classmethod
    def create(cls, commit=True, **kwargs):
        if 'id' not in kwargs:
            kwargs.update(dict(id=uuid64.issue()))
        instance = cls(**kwargs)

        if hasattr(instance, 'timestamp') \
                and getattr(instance, 'timestamp') is None:
            instance.timestamp = datetime.utcnow()

        return instance.save(commit=commit)

    @classmethod
    def get(cls, id):
        return cls.query.get(id)

    # We will also proxy Flask-SqlAlchemy's get_or_404
    # for symmetry
    @classmethod
    def get_or_404(cls, id):
        return cls.query.get_or_404(id)

    @classmethod
    def exists(cls, **kwargs):
        row = cls.query.filter_by(**kwargs).first()
        return row is not None

    def update(self, commit=True, **kwargs):
        for attr, value in kwargs.iteritems():
            setattr(self, attr, value)
        return commit and self.save() or self

    def save(self, commit=True):
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def delete(self, commit=True):
        db.session.delete(self)
        return commit and db.session.commit()


class User(db.Model, CRUDMixin, UserMixin):
    given_name = db.Column(db.String)
    family_name = db.Column(db.String)
    email = db.Column(db.String, unique=True)

    #: Arbitrary data
    data = db.Column(JsonType)

    accounts = db.relationship('Account', backref='user', lazy='dynamic')

    def __repr__(self):
        return 'User <{}>'.format(self.name)

    @property
    def name(self):
        # TODO: i18n
        return u'{}, {}'.format(self.family_name, self.given_name)


# TODO: Need a way to keep track of the value of volatile assets such as stocks
# TODO: Need a way to convert one asset's value to another (e.g., currency
# conversion, stock evaluation, etc.)


class Granularity(object):
    sec = '1sec'
    min = '1min'
    five_min = '5min'
    hour = '1hour'
    day = '1day'
    week = '1week'
    month = '1month'
    year = '1year'

    def is_valid(self, value):
        raise NotImplementedError


class AssetValue(db.Model, CRUDMixin):
    __table_args__ = (db.UniqueConstraint(
        'asset_id', 'evaluated_at', 'granularity'), {})

    asset_id = db.Column(db.BigInteger, db.ForeignKey('asset.id'))
    target_asset_id = db.Column(db.BigInteger, db.ForeignKey('asset.id'))
    target_asset = db.relationship('Asset', uselist=False,
                                   foreign_keys=[target_asset_id])
    evaluated_at = db.Column(db.DateTime(timezone=False))
    granularity = db.Column(db.Enum('1sec', '1min', '5min', '1hour', '1day',
                                    '1week', '1month', '1year',
                                    name='granularity'))
    open = db.Column(db.Numeric(precision=20, scale=4))
    high = db.Column(db.Numeric(precision=20, scale=4))
    low = db.Column(db.Numeric(precision=20, scale=4))
    close = db.Column(db.Numeric(precision=20, scale=4))


class Asset(db.Model, CRUDMixin):
    type = db.Column(db.Enum('currency', 'stock', 'bond', 'security', 'fund',
                             'commodity', name='asset_type'))
    name = db.Column(db.String)
    description = db.Column(db.Text)

    #: Arbitrary data
    data = db.Column(JsonType)

    asset_values = db.relationship(
        'AssetValue', backref='asset', foreign_keys=[AssetValue.asset_id],
        lazy='dynamic', cascade='all,delete-orphan')
    target_asset_values = db.relationship(
        'AssetValue', foreign_keys=[AssetValue.target_asset_id],
        lazy='dynamic', cascade='all,delete-orphan')
    records = db.relationship('Record', backref='asset',
                              lazy='dynamic', cascade='all,delete-orphan')

    def __repr__(self):
        return 'Asset <{} ({})>'.format(self.name, self.description)

    @property
    def unit_price(self):
        raise NotImplementedError

    @property
    def current_value(self):
        raise NotImplementedError


class Account(db.Model, CRUDMixin):
    user_id = db.Column(db.BigInteger, db.ForeignKey('user.id'))
    portfolio_id = db.Column(db.BigInteger, db.ForeignKey('portfolio.id'))
    type = db.Column(db.Enum('checking', 'savings', 'investment',
                             'credit_card', 'virtual', name='account_type'))
    name = db.Column(db.String)
    description = db.Column(db.Text)

    #: Arbitrary data
    data = db.Column(JsonType)

    # NOTE: Transaction-Account relationship is many-to-many
    # transactions = db.relationship('Transaction', backref='account',
    #                                lazy='dynamic')
    records = db.relationship('Record', backref='account',
                              lazy='dynamic')

    def __repr__(self):
        return 'Account <{} ({})>'.format(self.name, self.type)

    def balance(self, evaluated_at=None):
        """Calculates the account balance on a given date."""
        if not evaluated_at:
            evaluated_at = datetime.utcnow()

        # FIMXE: Consider open transactions
        records = Record.query.filter(
            Record.account == self,
            Record.created_at <= evaluated_at)

        # Sum all transactions to produce {asset: sum(quantity)} dictionary
        bs = {}
        rs = [(r.asset, r.quantity) for r in records]
        for asset, quantity in rs:
            bs.setdefault(asset, 0)
            bs[asset] += quantity
        return bs

    def net_worth(self, evaluated_at=None, granularity=Granularity.day,
                  approximation=False, target_asset=None):
        """Calculates the net worth of the account on a particular datetime.
        If approximation=True and the asset value record is unavailable for the
        given date (evaluated_at), try to pull the most recent AssetValue.
        """
        if target_asset is None:
            raise InvalidTargetAssetException('Target asset cannot be null')

        if not evaluated_at:
            evaluated_at = datetime.utcnow()

        if granularity == Granularity.day:
            # NOTE: Any better way to handle this?
            date = evaluated_at.date().timetuple()[:6]
            evaluated_at = datetime(*date)
        else:
            raise NotImplementedError

        net_asset_value = 0
        for asset, quantity in self.balance(evaluated_at).items():
            if asset == target_asset:
                net_asset_value += quantity
                continue

            asset_value = AssetValue.query \
                .filter(AssetValue.asset == asset,
                        AssetValue.granularity == granularity,
                        AssetValue.target_asset == target_asset)
            if approximation:
                asset_value = asset_value.filter(
                    AssetValue.evaluated_at <= evaluated_at) \
                    .order_by(AssetValue.evaluated_at.desc())
            else:
                asset_value = asset_value.filter(
                    AssetValue.evaluated_at == evaluated_at)

            asset_value = asset_value.first()

            if asset_value:
                worth = asset_value.close * quantity
            elif approximation:
                worth = 0
            else:
                raise AssetValueUnavailableException()
            net_asset_value += worth

        return net_asset_value


class Portfolio(db.Model, CRUDMixin):
    """A collection of accounts (= a collection of assets)."""
    __table_args__ = (
        db.ForeignKeyConstraint(['target_asset_id'], ['asset.id']),
    )
    name = db.Column(db.String)
    description = db.Column(db.String)
    accounts = db.relationship('Account', backref='portfolio', lazy='dynamic')
    target_asset_id = db.Column(db.BigInteger)
    target_asset = db.relationship('Asset', uselist=False,
                                   foreign_keys=[target_asset_id])

    def add_accounts(self, *accounts, commit=True):
        self.accounts.extend(accounts)
        if commit:
            db.session.commit()

    def net_worth(self, evaluated_at=None, granularity=Granularity.day):
        """Calculates the net worth of the portfolio on a particular datetime.
        """
        net = 0
        for account in self.accounts:
            net += account.net_worth(evaluated_at, granularity, True,
                                     self.target_asset)
        return net


class Transaction(db.Model, CRUDMixin):
    """A transaction consists of multiple records."""
    initiated_at = db.Column(db.DateTime(timezone=False))
    closed_at = db.Column(db.DateTime(timezone=False))
    state = db.Column(db.Enum('initiated', 'closed', 'pending', 'invalid',
                              name='transaction_state'))
    #: Individual record
    records = db.relationship('Record', backref='transaction',
                              lazy='dynamic')

    def __init__(self, initiated_at=None, *args, **kwargs):
        if initiated_at:
            self.initiated_at = initiated_at
        else:
            self.initiated_at = datetime.utcnow()
        self.state = 'initiated'
        super(self.__class__, self).__init__(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        """Implicitly mark the transaction as closed only if the state is
        'initiated'."""
        if self.state == 'initiated':
            self.close()

    def close(self, closed_at=None, commit=True):
        """Explicitly close a transaction."""
        if closed_at:
            self.closed_at = closed_at
        else:
            self.closed_at = datetime.utcnow()
        self.state = 'closed'

        if commit:
            db.session.commit()


class Record(db.Model, CRUDMixin):
    account_id = db.Column(db.BigInteger, db.ForeignKey('account.id'))
    asset_id = db.Column(db.BigInteger, db.ForeignKey('asset.id'))
    # asset = db.relationship(Asset, uselist=False)
    transaction_id = db.Column(db.BigInteger, db.ForeignKey('transaction.id'))
    type = db.Column(db.Enum('deposit', 'withdraw', 'balance_adjustment',
                             name='record_type'))
    # NOTE: We'll always use the UTC time
    created_at = db.Column(db.DateTime(timezone=False))
    category = db.Column(db.String)
    quantity = db.Column(db.Numeric(precision=20, scale=4))

    def __init__(self, *args, **kwargs):
        # Record.type could be 'balance_adjustment'
        if 'type' not in kwargs:
            if kwargs['quantity'] < 0:
                kwargs['type'] = 'withdraw'
            else:
                kwargs['type'] = 'deposit'
        super(self.__class__, self).__init__(*args, **kwargs)
