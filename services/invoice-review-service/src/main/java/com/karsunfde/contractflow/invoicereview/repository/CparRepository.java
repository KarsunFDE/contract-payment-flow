package com.karsunfde.contractflow.invoicereview.repository;

import com.karsunfde.contractflow.invoicereview.model.Cpar;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.List;

public interface CparRepository extends MongoRepository<Cpar, String> {
    List<Cpar> findByContractId(String contractId);
    List<Cpar> findByVendorId(String vendorId);
}
