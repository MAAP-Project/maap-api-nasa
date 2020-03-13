# from api.maap_database import db
# from datetime import datetime
#
#
# class MemberCmrGranule(db.Model):
#     __tablename__ = 'member_cmr_granule'
#
#     id = db.Column(db.Integer, primary_key=True)
#     collection_id = db.Column(db.Integer, db.ForeignKey('member_cmr_collection.id'), nullable=False)
#     granule_ur = db.Column(db.String())
#     creation_date = db.Column(db.DateTime())
#
#     collection = db.relationship('MemberCmrCollection', backref=db.backref('member_granule_collection', lazy=True))
#
#     def __init__(self, collection_id, granule_ur):
#         self.collection_id = collection_id
#         self.granule_ur = granule_ur
#         self.creation_date = datetime.utcnow()
#
#     def __repr__(self):
#         return '<MemberCmrGranule %r>' % self.granule_ur
