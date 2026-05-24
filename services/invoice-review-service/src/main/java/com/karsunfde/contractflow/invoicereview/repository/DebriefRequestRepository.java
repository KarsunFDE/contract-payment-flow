package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.DebriefRequest;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface DebriefRequestRepository extends MongoRepository<DebriefRequest, String> {
    List<DebriefRequest> findByAwardId(String awardId);
}
